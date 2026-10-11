# Windows 11 安装版

普通用户可直接下载 [Windows 发布包](https://github.com/cyberElar/tls-wifi-auto-connection/releases/latest)，
完整解压后双击 `CampusLoginSetup.exe`，允许管理员权限提示，填写账号密码并点击安装。
发布包自带运行环境，无需安装 Python。详见 [发布包使用说明](README.release.md)。
以下手动安装步骤适用于源码版。

`install-campus-login.ps1` 用 Windows 任务计划程序替代原安装脚本的 systemd 服务；
`run-campus-login.ps1` 负责后台启动登录程序、记录输出，并在进程退出后等待 10 秒重启。
开机任务使用 SYSTEM 身份，无需用户登录，不弹出窗口，使用电池时也运行。

`campus-login.py` 已加入 Windows 支持；`campus_login_windows.py` 使用 Windows 原生 API
检测网卡、IPv4 地址和当前 Wi-Fi。登录程序沿用原来的深信服认证协议，支持：

```text
python campus-login.py --watch Tsinglan-School -i "Wi-Fi" --cred credentials.json
```

Windows 请求绑定校园 Wi-Fi 的 IPv4 地址，并通过 `IP_UNICAST_IF` 指定出口网卡；
不使用系统代理、不通过域名解析门户地址，也不跟随探测请求的重定向。
这可以避开普通 TUN 路由，第三方底层流量过滤仍可能拦截请求。
程序不会更改系统路由或关闭 FlClash；无需安装任何第三方 Python 包。

Windows 11 若禁止读取 SSID，会尝试读取该网卡当前的 Windows 网络配置名称。
`-Network` 需要匹配该名称或 SSID。若两种查询都失败，日志会提示检查定位访问权限和网络配置。
Windows 网络配置名称可能带数字后缀，与 SSID 不完全相同。可用
`Get-NetConnectionProfile | Select-Object InterfaceAlias, Name` 查看，
然后通过 `-Network` 传入对应的完整名称。

## 安装

1. 在 [GitHub 仓库](https://github.com/cyberElar/tls-wifi-auto-connection) 点击 **Code → Download ZIP**，
   下载并解压完整仓库；也可使用 Git 克隆。确认解压后的项目目录包含 `campus-login.py`、
   `campus_login_windows.py`、`install-campus-login.ps1` 和 `run-campus-login.ps1` 四个文件。
2. 安装 **供所有用户使用** 的 Python 3.11 或更新版本，不能使用用户目录内的安装或 WindowsApps 商店别名。
3. 在普通 PowerShell 中切换到项目目录并检查安装脚本。以下示例假设 ZIP 解压在“下载”目录，
   请将路径改为你实际解压的位置：

   ```powershell
   Set-Location "$env:USERPROFILE\Downloads\tls-wifi-auto-connection-main"
   Test-Path -LiteralPath .\install-campus-login.ps1 -PathType Leaf
   ```

   检查结果应为 `True`。

4. 在同一个终端中运行 `python .\campus-login.py --save-only`，按提示输入账号和密码。
   保存过程不联系认证门户，密码输入不回显，凭据文件只允许当前用户访问。
   也可以准备 UTF-8 JSON 文件，格式为 `{"user":"账号","password":"密码"}`。
   默认读取当前用户目录下的 `.campus-login`，也可用 `-CredentialPath` 指定。
5. 以管理员身份重新打开 PowerShell，**再次切换到同一个项目目录**，然后执行：

   ```powershell
   Set-Location "$env:USERPROFILE\Downloads\tls-wifi-auto-connection-main"
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-campus-login.ps1
   ```

若提示找不到 `install-campus-login.ps1`，先运行 `Get-Location` 和上面的 `Test-Path` 检查。
`.\` 表示当前终端所在目录；新开的管理员终端可能从 `C:\Windows\System32` 等目录开始，
需要重新进入包含安装脚本的项目目录。若下载目录中确实缺少文件，请重新下载并完整解压
[最新仓库 ZIP](https://github.com/cyberElar/tls-wifi-auto-connection/archive/refs/heads/main.zip)，
或在已有 Git 仓库中执行 `git pull --ff-only` 更新。

指定其他文件、SSID 和网卡的例子：

```powershell
python .\campus-login.py --list-interfaces

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-campus-login.ps1 `
    -CredentialPath '.\credentials.json' `
    -LoginScript '.\campus-login.py' `
    -Network 'Tsinglan-School' `
    -Interface 'WLAN' `
    -PythonPath 'C:\Python314\python.exe'
```

Python 路径应改为实际安装路径。未指定 `-Interface` 时忽略 `Not Present` 的设备记录，
优先选择唯一在线的物理 Wi-Fi 网卡；没有在线网卡时，选择唯一仍在场的物理 Wi-Fi 网卡。
无法唯一确定时会列出候选网卡并要求显式指定。也支持原脚本的 `CAMPUS_NETWORK` 和 `CAMPUS_IFACE` 环境变量，
但网卡值应为 Windows 网卡名称。

`-WhatIf` 只预览安装，不改文件或任务，但仍需提供有效的依赖和凭据；
`-NoStart` 注册开机任务但暂不启动。正常安装立即启动，重复安装会更新并重启已有任务。
重新安装时，若默认凭据文件不存在，会复用已安装的凭据；显式指定的凭据路径不存在则报错。

程序、配置、凭据和日志存放于 `%ProgramData%\CampusLogin`，通常是 `C:\ProgramData\CampusLogin`。
该目录只允许 SYSTEM 和管理员访问，凭据保持原来的 JSON 格式，不是加密存储。
**账号和密码的完整保存路径为 `C:\ProgramData\CampusLogin\credentials.json`**
（即 `%ProgramData%\CampusLogin\credentials.json`）：`user` 字段存账号，`password` 字段存密码。
卸载开机任务会保留此文件；如需同时删除账号密码，卸载后用管理员权限删除安装目录。
安装前会检查缺失文件、凭据结构、Python 版本和网卡选择。

## 查看与卸载

先用网卡实际名称检查网络状态（不提交账号密码）：

```powershell
python .\campus-login.py --status -i 'WLAN'
```

以下任务和日志命令在管理员 PowerShell 中运行：

```powershell
Get-ScheduledTask -TaskName CampusLogin
Get-ScheduledTaskInfo -TaskName CampusLogin
Get-Content "$env:ProgramData\CampusLogin\campus-login.log" -Tail 30 -Wait

Stop-ScheduledTask -TaskName CampusLogin
Start-ScheduledTask -TaskName CampusLogin

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-campus-login.ps1 -Uninstall
```

日志包含登录程序的输出、退出和重试信息，达到约 5 MB 时保留一份轮换日志。
任务显示 `Running` 只说明后台进程在运行，是否认证成功需查看日志。
卸载会停止并移除任务，保留安装目录和凭据；确认不再使用后可自行删除该目录。

任务参数的官方参考：[Register-ScheduledTask](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/register-scheduledtask)、
[New-ScheduledTaskSettingsSet](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset)。

## 验证

```powershell
python -m unittest discover -s tests -v
```

测试使用临时虚拟凭据与测试登录程序，不注册真实任务、不连接认证门户。
已检查 Windows PowerShell 5.1 语法及任务参数，并验证本机的 Wi-Fi 识别和只读状态探测。
自动化测试覆盖认证报文、网卡绑定、代理绕过、重定向、凭据检查、安装预览、
标准错误记录、进程重试和日志轮换。实际账号认证和开机后台运行仍需在目标机器上验证。
