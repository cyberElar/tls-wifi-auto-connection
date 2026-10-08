import ctypes as ct
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import struct
import threading
import unittest
from unittest.mock import Mock, patch

import campus_login_windows as windows


GUID = "{00112233-4455-6677-8899-aabbccddeeff}"
WIFI = windows.Adapter("校园 WLAN", GUID, 7, ("10.0.0.2",), 71, True)


class WindowsNetworkTests(unittest.TestCase):
    def test_selects_wifi_by_name_guid_and_active_adapter(self):
        down = windows.Adapter("Other Wi-Fi", GUID + "x", 8, (), 71, False)
        tunnel = windows.Adapter("tun", GUID + "y", 9, ("198.18.0.1",), 53, True)
        with patch.object(windows, "adapters", return_value=[down, tunnel, WIFI]):
            self.assertEqual(windows.select_adapter(), WIFI)
            self.assertEqual(windows.select_adapter("校园 wlan"), WIFI)
            self.assertEqual(windows.select_adapter(GUID.upper()), WIFI)
            with self.assertRaises(OSError):
                windows.select_adapter("missing")

    def test_disconnected_adapter_does_not_query_wlan(self):
        down = windows.Adapter("WLAN", GUID, 7, (), 71, False)
        with patch.object(ct, "WinDLL", create=True) as api:
            self.assertEqual(windows.current_network(down), ("", ""))
            api.assert_not_called()

    def test_denied_wlan_access_uses_active_profile(self):
        api = Mock()
        api.WlanOpenHandle.return_value = 5
        with patch.object(ct, "WinDLL", return_value=api, create=True), \
             patch.object(windows, "network_profile", return_value=("Tsinglan-School", "")) as fallback:
            self.assertEqual(windows.current_network(WIFI), ("Tsinglan-School", ""))
            fallback.assert_called_once_with(7)

    def test_profile_fallback_accepts_unicode_and_rejects_no_active_profile(self):
        with patch.object(windows, "run_powershell", return_value='["校园网络"]'):
            self.assertEqual(windows.network_profile(7), ("校园网络", ""))
        for output in ("", "null", "[]", '["A", "B"]'):
            with self.subTest(output=output), patch.object(windows, "run_powershell", return_value=output):
                with self.assertRaises(OSError):
                    windows.network_profile(7)

    def test_wlan_reads_profile_ssid_and_frees_memory(self):
        connection = windows.WlanConnectionPrefix()
        connection.state = 1
        connection.profile = "School profile"
        ssid = b"Tsinglan-School"
        connection.ssid.length = len(ssid)
        connection.ssid.data[:len(ssid)] = ssid
        api = Mock()

        def open_handle(version, reserved, negotiated, handle):
            ct.cast(handle, ct.POINTER(ct.c_void_p))[0] = 123
            return 0

        def query(handle, guid, opcode, reserved, size, data, value_type):
            ct.cast(size, ct.POINTER(windows.DWORD))[0] = ct.sizeof(connection)
            ct.cast(data, ct.POINTER(ct.c_void_p))[0] = ct.addressof(connection)
            return 0

        api.WlanOpenHandle.side_effect = open_handle
        api.WlanQueryInterface.side_effect = query
        with patch.object(ct, "WinDLL", return_value=api, create=True):
            self.assertEqual(windows.current_network(WIFI), ("School profile", "Tsinglan-School"))
        api.WlanFreeMemory.assert_called_once()
        api.WlanCloseHandle.assert_called_once()

    def test_socket_pins_interface_in_network_byte_order_and_source_address(self):
        sock = Mock()
        with patch.object(windows.socket, "socket", return_value=sock):
            connection = windows.InterfaceHTTPConnection("4.3.2.1", 80, "10.0.0.2", 7, 5)
            connection.connect()
        sock.setsockopt.assert_called_once_with(socket.IPPROTO_IP, 31, struct.pack("!I", 7))
        sock.bind.assert_called_once_with(("10.0.0.2", 0))
        sock.connect.assert_called_once_with(("4.3.2.1", 80))

    def test_socket_binding_failure_closes_socket_without_fallback(self):
        sock = Mock()
        sock.bind.side_effect = OSError("lost DHCP address")
        with patch.object(windows.socket, "socket", return_value=sock):
            connection = windows.InterfaceHTTPConnection("4.3.2.1", 80, "10.0.0.2", 7, 5)
            with self.assertRaises(OSError):
                connection.connect()
        sock.close.assert_called_once()
        sock.connect.assert_not_called()

    def test_request_rejects_dns_and_ambiguous_source(self):
        with self.assertRaises(ValueError):
            windows.request("10.0.0.2", "http://example.com/", 5)
        with self.assertRaises(ValueError):
            windows.request("10.0.0.2", "https://4.3.2.1/", 5)
        with patch.object(windows, "adapters", return_value=[WIFI, WIFI]):
            with self.assertRaises(OSError):
                windows.request("10.0.0.2", "http://4.3.2.1/", 5)

    @unittest.skipUnless(os.name == "nt", "Requires the Windows IP helper API")
    def test_native_http_ignores_proxy_and_does_not_follow_redirects(self):
        visited = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                visited.append(self.path)
                self.send_response(302)
                self.send_header("Location", "http://4.3.2.1/ac_portal/login.php")
                self.end_headers()

            def do_POST(self):
                visited.append(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"msg": "测试"}, ensure_ascii=False).encode("utf-8"))

            def log_message(self, *args):
                pass

        loopback = next(item for item in windows.adapters() if "127.0.0.1" in item.addresses)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = "http://127.0.0.1:%d/" % server.server_port
            with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9"}):
                status, redirect, body = windows.request("127.0.0.1", url, 5, iface=loopback.name)
                self.assertEqual(status, 302)
                self.assertIn("ac_portal", redirect)
                self.assertEqual(visited, ["/"])
                _, _, body = windows.request("127.0.0.1", url, 5, body=b"opr=pwdLogin", iface=loopback.name)
                self.assertEqual(json.loads(body), {"msg": "测试"})
                self.assertEqual(visited[-1], b"opr=pwdLogin")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
