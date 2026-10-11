# TLS 校园网自动登录 — Windows 双击安装版

适用于 Windows 11 x64。发布包自带运行环境，无需安装 Python，也无需手动运行 PowerShell。

## 安装和更新

1. 将整个 ZIP 解压到任意文件夹，保留 `CampusLoginSetup.exe` 和 `_internal` 目录在一起。
2. 双击 `CampusLoginSetup.exe`，允许 Windows 管理员权限提示。
3. 输入校园账号、密码和校园网络名称，确认 Wi-Fi 网卡，然后点击“安装 / 更新并启用”。
4. 后台任务立即启动，重启后也会在用户登录 Windows 前运行。认证结果请点击“打开日志目录”，
   查看 `campus-login.log`。安装成功只表示任务配置完成。

校园网络名称默认为 `Tsinglan-School`。若 Windows 的网络配置名称带有数字后缀，
请填写实际的名称或 Wi-Fi SSID。更换账号密码时，再次运行安装器并重新填写即可。

## 账号密码保存在哪里

账号和密码保存在 `%ProgramData%\CampusLogin\credentials.json`，通常是：

```text
C:\ProgramData\CampusLogin\credentials.json
```

这是 UTF-8 JSON 文件，`user` 字段存账号，`password` 字段存密码。密码不是加密存储；
文件及安装目录仅允许 SYSTEM 和管理员访问。密码不会写入命令行参数或安装日志。
安装时的临时凭据文件在写入前限制访问权限，并在操作结束后删除。

其他文件也在同一目录：`config.json` 保存网络和网卡配置，`campus-login.log` 保存运行日志，
`campus-login.exe` 和 `run-campus-login.ps1` 是开机后台程序。

## 卸载

再次双击 `CampusLoginSetup.exe` 并点击“卸载开机任务”，或双击 `Uninstall.cmd`。
卸载会停止自动登录并移除任务，保留账号密码、配置和日志。
确认不再使用后，可在管理员权限下删除 `C:\ProgramData\CampusLogin`，同时删除保存的账号密码。

安装完成后可以删除下载解压的发布包，后台任务从 ProgramData 中运行。
