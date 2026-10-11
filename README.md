# TLS Wi-Fi Auto Connection

Automatic login for the Tsinglan-School Sangfor AC captive portal. The client
waits for the configured campus Wi-Fi, checks whether the portal blocks access,
and signs in using locally stored credentials. Failed logins back off to avoid
rapid retries with an incorrect password.

The Windows 11 version runs silently at startup through Task Scheduler. Linux
uses the original Fedora/systemd installer. One-shot login also supports macOS.

## Windows double-click release / Windows 双击安装版

Download `CampusLogin-v1.0.0-windows-x64.zip` from
[Releases](https://github.com/cyberElar/tls-wifi-auto-connection/releases/latest),
extract the entire ZIP, then double-click **CampusLoginSetup.exe**. Allow the
administrator prompt, enter your campus username and password, confirm the
network name and Wi-Fi adapter, and click **安装 / 更新并启用**. The release bundles
its runtime, so Python is not required. Keep the `_internal` folder next to the
setup executable until installation finishes.

下载发布包并完整解压，双击 **CampusLoginSetup.exe**，填写账号密码后点击安装即可。
安装窗口提供卸载按钮，包内的 `Uninstall.cmd` 也可用于卸载。
See [the release guide / 发布包使用说明](README.release.md).

**Account and password storage / 账号密码存储位置:**
`%ProgramData%\CampusLogin\credentials.json`, normally
`C:\ProgramData\CampusLogin\credentials.json`. The UTF-8 JSON fields are `user`
(account) and `password` (password). Credentials are stored without encryption;
only SYSTEM and administrators can access the file and installation directory.
Uninstalling the task retains this file. Delete the installation directory with
administrator privileges when you also want to remove the saved credentials.

账号、密码分别保存在该 JSON 文件的 `user` 和 `password` 字段中。卸载开机任务会保留凭据，
确认不再使用后可使用管理员权限删除 `C:\ProgramData\CampusLogin`。

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

## Building a Windows release

On Windows x64 with Python 3.14:

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv-build\Scripts\python.exe .\build_windows_release.py
```

The ZIP and its SHA-256 checksum are written to `dist`. The build launches the
bundled GUI and checks its assets, then checks the worker executable without
installing a task or authenticating an account.

API references: [Windows IP socket options](https://learn.microsoft.com/en-us/windows/win32/winsock/ipproto-ip-socket-options),
[GetAdaptersAddresses](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getadaptersaddresses),
[WlanQueryInterface](https://learn.microsoft.com/en-us/windows/win32/api/wlanapi/nf-wlanapi-wlanqueryinterface).
