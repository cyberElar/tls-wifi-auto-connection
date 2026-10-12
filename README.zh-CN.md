# TLS Wi-Fi Auto Connection

[English](README.md) | 简体中文

为 Tsinglan-School 校园 Wi-Fi 的深信服 AC 认证门户提供自动登录。程序等待连接到指定的
校园网络，检查是否需要认证，并使用本地保存的账号密码登录。认证失败后逐步延长重试间隔，
避免密码错误时频繁重试。

Windows 11 版通过任务计划程序在开机后静默运行；Linux 使用原有的 Fedora/systemd 安装方式，
macOS 支持手动单次登录。

## Windows 双击安装版

从 [Releases](../../releases/latest) 下载单个文件
`CampusLoginSetup-v<版本>-windows-x64.exe`，双击运行。若出现“Windows 已保护你的电脑”，
点 **更多信息 → 仍要运行**（程序没有代码签名）。允许管理员权限提示，填写校园账号和密码，
点击 **安装 / 更新并启用**。校园网络名称和 Wi-Fi 网卡一般会自动填好。

程序自带运行环境，无需另装 Python。“查看运行状态”会显示后台任务是否在运行，
并用中文解释最近一条日志；“卸载”可选择是否同时删除保存的账号密码和日志。
详见 [发布包使用说明](README.release.md)。

**账号和密码的保存位置：** `%ProgramFiles%\CampusLogin\credentials.json`，通常为：

```text
C:\Program Files\CampusLogin\credentials.json
```

文件采用 UTF-8 JSON 格式，`user` 字段存账号，`password` 字段存密码。
凭据不是加密存储；文件及安装目录仅允许 SYSTEM 和管理员访问。
卸载时选择删除数据（或给 PowerShell 安装脚本加 `-RemoveData`）会一并删除凭据文件，
否则保留。

1.1.0 之前的版本安装在 `%ProgramData%\CampusLogin`。普通用户可以在 ProgramData 下新建文件夹，
预先建好的目录里可能留有会被 SYSTEM 任务执行的文件；1.1.0 改为安装到 Program Files，
并在安装成功后删除旧目录里的文件。

## Windows 11 源码安装

以下步骤适用于直接运行源码。希望双击安装的用户，请使用上面的 Windows 发布包。

在 GitHub 仓库点击 **Code → Download ZIP** 并完整解压，或使用 Git 克隆仓库。
确认项目目录中包含以下四个文件：

- `campus-login.py`
- `campus_login_windows.py`
- `install-campus-login.ps1`
- `run-campus-login.ps1`

安装 **供所有用户使用** 的 Python 3.11 或更新版本，无需第三方 Python 包。
打开普通 PowerShell，进入解压后的项目目录。以下示例假设 ZIP 解压在“下载”目录，
请将路径改为实际位置：

```powershell
Set-Location "$env:USERPROFILE\Downloads\tls-wifi-auto-connection-main"
Test-Path -LiteralPath .\install-campus-login.ps1 -PathType Leaf
```

检查结果应为 `True`。接着保存账号密码并查看网卡名称：

```powershell
python .\campus-login.py --save-only
python .\campus-login.py --list-interfaces
```

保存时会交互式询问密码，不回显，也不会将密码放入命令历史。
然后以 **管理员身份** 重新打开 PowerShell，再次切换到同一个项目目录并安装：

```powershell
Set-Location "$env:USERPROFILE\Downloads\tls-wifi-auto-connection-main"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-campus-login.ps1
```

若提示找不到 `install-campus-login.ps1`，运行 `Get-Location` 并重复上面的 `Test-Path` 检查。
`.\` 表示当前终端所在目录；新开的管理员终端可能进入了其他目录。
若下载目录中确实缺少脚本，请重新完整解压仓库 ZIP，或在 Git 仓库中执行
`git pull --ff-only` 更新。

安装器优先选择唯一在线的物理 Wi-Fi 网卡，并忽略状态为 `Not Present` 的设备。
若没有在线网卡，则选择唯一仍在场的物理 Wi-Fi 网卡。无法唯一确定时，使用
`-Interface 'WLAN'` 或 `-Interface 'Wi-Fi'` 指定 Windows 网卡名称。
若 Python 不在 PATH 中，可使用 `-PythonPath` 指定安装路径。

配置、凭据和日志保存在 `%ProgramFiles%\CampusLogin`，仅 SYSTEM 和管理员可访问。
开机任务以 SYSTEM 身份运行，包括用户登录 Windows 之前。

手动检查网络状态：

```powershell
python .\campus-login.py --status -i 'WLAN'
```

卸载开机任务，保留安装文件和凭据：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-campus-login.ps1 -Uninstall
```

安装参数、日志查看及故障排查详见 [Windows 安装说明](README.windows.md)。

## 网络行为

Windows 使用原生 IP Helper 和 WLAN API 检测网卡及 SSID，不依赖 `netsh` 输出语言。
若 Windows 拒绝读取 SSID，程序会通过 `Get-NetConnectionProfile` 读取活动网络配置名称。
`--watch` 指定的校园网络名称需要匹配该名称或 SSID。

Windows HTTP 请求绑定 Wi-Fi 网卡的 IPv4 地址，并使用 `IP_UNICAST_IF` 指定出口网卡。
程序忽略代理设置，直接使用 IPv4 地址，不跟随重定向，不修改系统路由，也不关闭 FlClash。
这可以避开普通 TUN 路由；第三方底层流量过滤仍可能拦截请求。
Linux/macOS 继续使用绑定源地址的 `curl`。

本项目针对原脚本使用的校园认证门户和 RC4 请求格式，不是通用校园网认证客户端。
账号密码保存为具有受限访问权限的 JSON 文件，不加密存储；门户原有的密码编码方式保持不变。

## Linux 和 macOS

交互式保存账号密码：

```sh
python3 campus-login.py --save-only
```

在 Fedora 中指定网卡名称并运行原安装脚本：

```sh
sudo CAMPUS_IFACE=wlp0s20f3 bash install-campus-login.sh
```

在 macOS 中指定 Wi-Fi 网卡并手动登录：

```sh
python3 campus-login.py -i en1
```

## 测试

```powershell
python -m unittest discover -s tests -v
```

测试使用虚拟凭据和本地 HTTP 服务，覆盖门户报文、响应解析、网卡选择、出口网卡及源地址绑定、
代理绕过、重定向处理、凭据验证、离开校园网络时的行为、重试间隔和 Windows 后台监管程序。
测试不会认证真实账号或注册开机任务。

已在开发机器上检查 Windows 原生 Wi-Fi 识别和只读网络状态探测。
真实账号认证及开机运行仍需在目标机器上验证。

## 构建 Windows 发布包

在 Windows x64 中使用 Python 3.14 执行：

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv-build\Scripts\python.exe .\build_windows_release.py
```

单个安装程序 EXE、SHA-256 校验文件和第三方许可说明输出到 `dist` 目录。构建过程会启动打包后的安装窗口，检查所需文件，
并验证后台 EXE；不会注册开机任务或使用真实账号认证。

API 参考：[Windows IP socket options](https://learn.microsoft.com/en-us/windows/win32/winsock/ipproto-ip-socket-options)、
[GetAdaptersAddresses](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getadaptersaddresses)、
[WlanQueryInterface](https://learn.microsoft.com/en-us/windows/win32/api/wlanapi/nf-wlanapi-wlanqueryinterface)。
