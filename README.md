# TLS Wi-Fi Auto Connection

English | [简体中文](README.zh-CN.md)

Automatic login for the Tsinglan-School Sangfor AC captive portal. The client
waits for the configured campus Wi-Fi, checks whether the portal blocks access,
and signs in using locally stored credentials. Failed logins back off to avoid
rapid retries with an incorrect password.

The Windows 11 version runs silently at startup through Task Scheduler. Linux
uses the original Fedora/systemd installer. One-shot login also supports macOS.

## Windows double-click release

Download the single file `CampusLoginSetup-v<version>-windows-x64.exe` from
[Releases](../../releases/latest) and double-click it. If SmartScreen shows
"Windows protected your PC", choose **More info → Run anyway** (the program is
not code-signed). Allow the administrator prompt, enter your campus username and
password, and click the primary install/update button. The network name and
Wi-Fi adapter are filled in automatically in most cases. The executable bundles
its runtime, so Python is not required.

The installer supports English and Simplified Chinese. Use **语言 / Language**
to switch immediately; the first launch follows your Windows display language
(Chinese uses Simplified Chinese, other languages use English). Your choice is
remembered in `%LOCALAPPDATA%\CampusLogin\setup-preferences.json`, separately from
account credentials. **View status** shows whether the background task is running
and explains its latest log entry in the selected language. **Uninstall** removes
the startup task and can also delete saved credentials and logs.
See [the release guide (in Chinese)](README.release.md).

**Account and password storage:**
`%ProgramFiles%\CampusLogin\credentials.json`, normally
`C:\Program Files\CampusLogin\credentials.json`. The UTF-8 JSON fields are `user`
(account) and `password` (password). Credentials are stored without encryption;
only SYSTEM and administrators can access the file and installation directory.
Uninstalling keeps this file unless you choose to delete the saved data (or pass
`-RemoveData` to the PowerShell installer).

Versions before 0.2.0 (the v0.1.0 release) installed into `%ProgramData%\CampusLogin`. Standard users
can create folders under ProgramData, so a pre-created folder could hold files
that the SYSTEM task would then run; 0.2.0 installs under Program Files instead
and deletes the old files after a successful install.

## Windows 11 quick start

The steps below are for running from source. For double-click installation, use
the release above.

Download the [complete repository ZIP](https://github.com/cyberElar/tls-wifi-auto-connection/archive/refs/heads/main.zip)
using **Code → Download ZIP** and extract it, or clone this repository with Git.
The project folder must contain `campus-login.py`, `campus_login_windows.py`,
`install-campus-login.ps1`, and `run-campus-login.ps1` together.

Install Python 3.11 or newer **for all users**. No third-party Python packages
are required. Open PowerShell and change to the extracted project folder. For
example, if you extracted the ZIP into Downloads:

```powershell
Set-Location "$env:USERPROFILE\Downloads\tls-wifi-auto-connection-main"
Test-Path -LiteralPath .\install-campus-login.ps1 -PathType Leaf
```

Adjust the path to your actual project folder. The check must return `True`.

First save your credentials from a regular PowerShell terminal. The password is
prompted without displaying it or putting it in shell history:

```powershell
python .\campus-login.py --save-only
python .\campus-login.py --list-interfaces
```

Then open PowerShell **as administrator**, change to the same project folder
again, and install:

```powershell
Set-Location "$env:USERPROFILE\Downloads\tls-wifi-auto-connection-main"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-campus-login.ps1
```

If PowerShell reports that `install-campus-login.ps1` does not exist, run
`Get-Location` and repeat the `Test-Path` check. The `.\` prefix refers to the
current terminal folder. A new administrator terminal may open in a different
folder. If the file is missing from your download, extract the complete ZIP
again or update your Git checkout with `git pull --ff-only`.

The installer prefers the only connected physical Wi-Fi adapter and ignores
devices marked `Not Present`. If none are connected, it selects the only remaining
physical Wi-Fi adapter. If the choice is ambiguous, specify its
Windows name with `-Interface 'WLAN'` or `-Interface 'Wi-Fi'`. Use `-PythonPath`
for a Python installation that is not on PATH. Configuration, credentials and
logs are stored under `%ProgramFiles%\CampusLogin`, accessible only to SYSTEM
and administrators. The startup task runs as SYSTEM, including before sign-in.

For a manual network status check:

```powershell
python .\campus-login.py --status -i 'WLAN'
```

Uninstall the task (installed files and credentials are retained):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-campus-login.ps1 -Uninstall
```

See [the detailed Windows guide (in Chinese)](README.windows.md) for
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

## Building a Windows release

On Windows x64 with Python 3.14:

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv-build\Scripts\python.exe .\build_windows_release.py
```

The single setup executable, its SHA-256 checksum and the third-party notices
are written to `dist`. The build launches the
bundled GUI and checks its assets, then checks the worker executable without
installing a task or authenticating an account.

API references: [Windows IP socket options](https://learn.microsoft.com/en-us/windows/win32/winsock/ipproto-ip-socket-options),
[GetAdaptersAddresses](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getadaptersaddresses),
[WlanQueryInterface](https://learn.microsoft.com/en-us/windows/win32/api/wlanapi/nf-wlanapi-wlanqueryinterface).
