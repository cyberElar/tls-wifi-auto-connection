"""Windows adapter/WLAN APIs and HTTP requests pinned to one interface.

Only the Python standard library is used. Network requests never follow
redirects, consult proxy settings, or resolve host names.
"""

import base64
import ctypes as ct
from dataclasses import dataclass
import http.client
import ipaddress
import json
import os
import socket
import struct
import subprocess
import urllib.parse
import uuid


DWORD = ct.c_uint32


class SocketAddress(ct.Structure):
    _fields_ = [("pointer", ct.c_void_p), ("length", ct.c_int)]


class UnicastAddress(ct.Structure):
    pass


UnicastAddress._fields_ = [
    ("length", DWORD), ("flags", DWORD),
    ("next", ct.POINTER(UnicastAddress)), ("address", SocketAddress),
    ("prefix_origin", DWORD), ("suffix_origin", DWORD), ("dad_state", DWORD),
]


class AdapterAddress(ct.Structure):
    pass


# Only the prefix of IP_ADAPTER_ADDRESSES_LH that we read is needed.
AdapterAddress._fields_ = [
    ("length", DWORD), ("index", DWORD), ("next", ct.POINTER(AdapterAddress)),
    ("guid", ct.c_char_p), ("unicast", ct.POINTER(UnicastAddress)),
    ("anycast", ct.c_void_p), ("multicast", ct.c_void_p), ("dns_server", ct.c_void_p),
    ("dns_suffix", ct.c_wchar_p), ("description", ct.c_wchar_p), ("name", ct.c_wchar_p),
    ("physical_address", ct.c_ubyte * 8), ("physical_address_length", DWORD),
    ("flags", DWORD), ("mtu", DWORD), ("kind", DWORD), ("status", DWORD),
]


class Dot11SSID(ct.Structure):
    _fields_ = [("length", DWORD), ("data", ct.c_ubyte * 32)]


class WlanConnectionPrefix(ct.Structure):
    _fields_ = [
        ("state", DWORD), ("mode", DWORD), ("profile", ct.c_wchar * 256),
        ("ssid", Dot11SSID),
    ]


@dataclass(frozen=True)
class Adapter:
    name: str
    guid: str
    index: int
    addresses: tuple
    kind: int
    connected: bool

    @property
    def address(self):
        return self.addresses[0] if self.connected and self.addresses else ""


def adapters():
    api = ct.WinDLL("iphlpapi.dll").GetAdaptersAddresses
    api.argtypes = [DWORD, DWORD, ct.c_void_p, ct.c_void_p, ct.POINTER(DWORD)]
    api.restype = DWORD
    size = DWORD(15 * 1024)
    for _ in range(3):
        buffer = ct.create_string_buffer(size.value)
        result = api(socket.AF_INET, 0x0E, None, buffer, ct.byref(size))
        if result != 111:  # ERROR_BUFFER_OVERFLOW; retry if adapters changed.
            break
    if result == 232:  # ERROR_NO_DATA
        return []
    if result:
        raise ct.WinError(result)
    found = []
    entry = ct.cast(buffer, ct.POINTER(AdapterAddress))
    while entry:
        item = entry.contents
        addresses = []
        address = item.unicast
        while address:
            unicast = address.contents
            if unicast.address.pointer and unicast.address.length >= 8 and unicast.dad_state == 4:
                raw = ct.string_at(unicast.address.pointer, 8)
                if struct.unpack_from("=H", raw)[0] == socket.AF_INET:
                    ipv4 = ipaddress.IPv4Address(raw[4:8])
                    if not ipv4.is_link_local and not ipv4.is_unspecified:
                        addresses.append(str(ipv4))
            address = unicast.next
        found.append(Adapter(item.name or "", (item.guid or b"").decode("ascii"),
                             item.index, tuple(addresses), item.kind, item.status == 1))
        entry = item.next
    return found


def select_adapter(iface=None):
    available = adapters()
    if iface:
        matches = [item for item in available if item.name.casefold() == iface.casefold()
                   or item.guid.casefold() == iface.casefold()]
    else:
        matches = [item for item in available if item.kind == 71]  # IF_TYPE_IEEE80211
        connected = [item for item in matches if item.connected]
        if len(connected) == 1:
            matches = connected
    if len(matches) != 1:
        raise OSError("Cannot select one Wi-Fi adapter; use -i with its Windows name "
                      "(list adapters with --list-interfaces).")
    return matches[0]


def run_powershell(script, env=None):
    executable = os.path.join(os.environ["SystemRoot"], "System32", "WindowsPowerShell",
                              "v1.0", "powershell.exe")
    script = "$ErrorActionPreference = 'Stop'; [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); " + script
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    environment = (env if env is not None else os.environ).copy()
    # A Python process launched from PowerShell 7 can inherit Core-only module
    # paths. Let Windows PowerShell 5.1 rebuild its own default module paths.
    environment.pop("PSModulePath", None)
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-OutputFormat", "Text", "-EncodedCommand", encoded],
        capture_output=True, encoding="utf-8", errors="replace", timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW, env=environment,
    )
    if result.returncode:
        raise OSError("Windows PowerShell could not read network information or set credential permissions.")
    return result.stdout.strip()


def network_profile(index):
    # Windows 11 can deny SSID access when location permission is disabled.
    # Network List Manager's active profile name does not expose a BSSID.
    output = run_powershell(
        "@(Get-NetConnectionProfile -InterfaceIndex %d -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty Name) | ConvertTo-Json -Compress" % index
    )
    names = (json.loads(output) or []) if output else []
    if isinstance(names, str):
        names = [names]
    if not isinstance(names, list) or len(names) != 1 or not isinstance(names[0], str):
        raise OSError("Cannot identify the active Wi-Fi network. Allow location access "
                      "in Windows Settings, or check the network profile name.")
    return names[0], ""


def current_network(adapter):
    if not adapter.connected:
        return "", ""
    api = ct.WinDLL("wlanapi.dll")
    api.WlanOpenHandle.argtypes = [DWORD, ct.c_void_p, ct.POINTER(DWORD), ct.POINTER(ct.c_void_p)]
    api.WlanOpenHandle.restype = DWORD
    api.WlanQueryInterface.argtypes = [ct.c_void_p, ct.c_void_p, DWORD, ct.c_void_p,
                                      ct.POINTER(DWORD), ct.POINTER(ct.c_void_p), ct.c_void_p]
    api.WlanQueryInterface.restype = DWORD
    api.WlanFreeMemory.argtypes = [ct.c_void_p]
    api.WlanFreeMemory.restype = None
    api.WlanCloseHandle.argtypes = [ct.c_void_p, ct.c_void_p]
    api.WlanCloseHandle.restype = DWORD
    version, handle, size, data = DWORD(), ct.c_void_p(), DWORD(), ct.c_void_p()
    result = api.WlanOpenHandle(2, None, ct.byref(version), ct.byref(handle))
    if result == 5:
        return network_profile(adapter.index)
    if result:
        raise ct.WinError(result)
    try:
        guid = (ct.c_ubyte * 16).from_buffer_copy(uuid.UUID(adapter.guid).bytes_le)
        result = api.WlanQueryInterface(handle, ct.byref(guid), 7, None,
                                        ct.byref(size), ct.byref(data), None)
        if result == 5023:  # ERROR_INVALID_STATE: disconnected during the query.
            return "", ""
        if result == 5:  # ERROR_ACCESS_DENIED: use the active network profile.
            return network_profile(adapter.index)
        if result:
            raise ct.WinError(result)
        if not data or size.value < ct.sizeof(WlanConnectionPrefix):
            raise OSError("Windows returned incomplete Wi-Fi connection information.")
        connection = ct.cast(data, ct.POINTER(WlanConnectionPrefix)).contents
        ssid = bytes(connection.ssid.data[:min(connection.ssid.length, 32)]).decode("utf-8", "replace")
        return connection.profile, ssid
    finally:
        if data:
            api.WlanFreeMemory(data)
        api.WlanCloseHandle(handle, None)


class InterfaceHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, source, index, timeout):
        super().__init__(host, port, timeout=timeout)
        self.source = source
        self.index = index

    def connect(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            # IP_UNICAST_IF = 31 in the Windows SDK; Python need not export it.
            sock.setsockopt(socket.IPPROTO_IP, 31, struct.pack("!I", self.index))
            sock.bind((self.source, 0))
            sock.connect((self.host, self.port))
        except BaseException:
            sock.close()
            raise
        self.sock = sock


def request(source, url, timeout, body=None, headers=None, iface=None, read_body=True):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.username or parsed.password:
        raise ValueError("Campus requests must use a plain HTTP URL with an IPv4 address.")
    ipaddress.IPv4Address(parsed.hostname)  # No DNS/fake-IP resolution.
    if iface:
        adapter = select_adapter(iface)
        matches = [adapter] if source in adapter.addresses else []
    else:
        matches = [item for item in adapters() if source in item.addresses]
    if len(matches) != 1:
        raise OSError("The Wi-Fi source address changed or is not unique; retry after DHCP settles.")
    connection = InterfaceHTTPConnection(parsed.hostname, parsed.port or 80, source,
                                         matches[0].index, timeout)
    try:
        path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        connection.request("POST" if body is not None else "GET", path, body=body, headers=headers or {})
        response = connection.getresponse()
        content = response.read(65536).decode(response.headers.get_content_charset() or "utf-8", "replace") if read_body else ""
        return response.status, response.getheader("Location", ""), content
    finally:
        connection.close()


def protect_credential(path):
    environment = os.environ.copy()
    environment["CAMPUS_CREDENTIAL_FILE"] = os.path.abspath(path)
    run_powershell(
        "$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User; "
        "$acl = [Security.AccessControl.FileSecurity]::new(); "
        "$acl.SetAccessRuleProtection($true, $false); $acl.SetOwner($sid); "
        "$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new("
        "$sid, [Security.AccessControl.FileSystemRights]::FullControl, "
        "[Security.AccessControl.AccessControlType]::Allow)); "
        "[IO.File]::SetAccessControl($env:CAMPUS_CREDENTIAL_FILE, $acl)",
        env=environment,
    )
