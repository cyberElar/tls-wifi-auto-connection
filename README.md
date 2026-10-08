# TLS Wi-Fi Auto Connection

Automatic login for the Tsinglan-School Sangfor AC captive portal. The client
waits for the configured campus Wi-Fi, checks whether the portal blocks access,
and signs in using locally stored credentials. Failed logins back off to avoid
rapid retries with an incorrect password.

The Windows 11 version runs silently at startup through Task Scheduler. Linux
uses the original Fedora/systemd installer. One-shot login also supports macOS.

## Windows 11 quick start

Install Python 3.11 or newer **for all users**, then keep the distribution's Python
and PowerShell files together. No third-party Python packages are required.

First save your credentials from a regular PowerShell terminal. The password is
prompted without displaying it or putting it in shell history:

```powershell
python .\campus-login.py --save-only
python .\campus-login.py --list-interfaces
```

Then open PowerShell **as administrator**, navigate to this project, and install:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-campus-login.ps1
```

The installer prefers the only connected physical Wi-Fi adapter and ignores
devices marked `Not Present`. If none are connected, it selects the only remaining
physical Wi-Fi adapter. If the choice is ambiguous, specify its
Windows name with `-Interface 'WLAN'` or `-Interface 'Wi-Fi'`. Use `-PythonPath`
for a Python installation that is not on PATH. Configuration, credentials and
logs are stored under `%ProgramData%\CampusLogin`, accessible only to SYSTEM
and administrators. The startup task runs as SYSTEM, including before sign-in.

For a manual network status check:

```powershell
python .\campus-login.py --status -i 'WLAN'
```

Uninstall the task (installed files and credentials are retained):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-campus-login.ps1 -Uninstall
```

See [the detailed Windows guide / Windows 中文说明](README.windows.md) for
installation options, log inspection, and troubleshooting.

## Network behavior

Windows uses native IP Helper and WLAN APIs, so adapter and SSID detection does
not depend on the language of `netsh` output. If Windows denies SSID access,
the client uses the active network profile name from `Get-NetConnectionProfile`.
The configured `--watch` value must match that name or the SSID.

Windows HTTP connections bind the Wi-Fi IPv4 address and set `IP_UNICAST_IF` to
select that adapter. The client ignores proxy settings, uses literal IPv4
addresses, and does not follow redirects. It does not modify routes or stop
FlClash. This avoids ordinary TUN routing; third-party packet filters can still
intercept or block traffic. Linux/macOS continue using source-bound `curl`.

This project targets the portal and RC4 request format already used by the
original script (`4.3.2.1/ac_portal/login.php`); it is not a general campus
portal client. Credentials are stored in JSON with restricted permissions,
not encrypted at rest. The portal's existing password encoding is preserved.

## Linux and macOS

Save credentials interactively:

```sh
python3 campus-login.py --save-only
```

On Fedora, configure the interface name and run the original installer:

```sh
sudo CAMPUS_IFACE=wlp0s20f3 bash install-campus-login.sh
```

For manual login on macOS, specify the Wi-Fi interface:

```sh
python3 campus-login.py -i en1
```

## Tests

```powershell
python -m unittest discover -s tests -v
```

The tests use dummy credentials and a local HTTP server. They cover portal
payloads, response parsing, adapter selection, interface/source binding, proxy
bypass, redirect handling, credential validation, off-campus behavior, bounded
retries, and the Windows supervisor. They do not authenticate a real account or
install a startup task.

Windows native Wi-Fi detection and the read-only status probe were also checked
on the development computer. Real account authentication and startup execution
still require verification on the target machine.

API references: [Windows IP socket options](https://learn.microsoft.com/en-us/windows/win32/winsock/ipproto-ip-socket-options),
[GetAdaptersAddresses](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getadaptersaddresses),
[WlanQueryInterface](https://learn.microsoft.com/en-us/windows/win32/api/wlanapi/nf-wlanapi-wlanqueryinterface).
