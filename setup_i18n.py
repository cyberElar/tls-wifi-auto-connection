"""Installer translations and per-user language preferences (never credentials)."""

import ctypes
import json
import os
from pathlib import Path


LANGUAGES = {"zh-CN": "简体中文", "en": "English"}
PREFERENCES = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "CampusLogin" / "setup-preferences.json"

STRINGS = {
    "zh-CN": {
        "window_title": "TLS 校园网自动登录 · {version}",
        "heading": "校园网自动登录",
        "introduction": "填好账号密码，点一次安装。以后开机会自动登录校园网。",
        "user": "校园账号",
        "password": "密码",
        "network": "校园网络名称 / SSID",
        "interface": "Wi-Fi 网卡",
        "network_hint": "网络名称应与校园 Wi-Fi 的 SSID 或 Windows 网络配置名称一致。",
        "install": "安装 / 更新并启用",
        "uninstall": "卸载",
        "view_status": "查看运行状态",
        "credential_notice": "账号密码文件：{path}\n仅 SYSTEM 和管理员可访问。",
        "detecting": "正在检测 Wi-Fi 网卡…",
        "ready": "就绪",
        "incomplete_title": "信息不完整",
        "incomplete": "请填写账号、密码、校园网络名称和 Wi-Fi 网卡。",
        "installing": "正在安装并启动后台任务…",
        "uninstall_prompt": "停止自动登录并移除开机任务。\n\n是否同时删除保存的账号密码和日志？\n"
                            "· 是：全部删除（推荐，不再使用时）\n· 否：只停止任务，保留账号密码\n· 取消：不卸载",
        "uninstalling": "正在停止并移除后台任务…",
        "reading_status": "正在读取运行状态…",
        "status_title": "运行状态",
        "task_state": "后台任务：{state}",
        "state_running": "正在运行",
        "state_ready": "已安装但没有运行（重启电脑后会启动）",
        "state_disabled": "已被禁用",
        "state_queued": "等待启动",
        "state_unknown": "状态未知",
        "state_absent": "未安装",
        "latest_result": "最近结果：{summary}",
        "no_records": "还没有记录，请稍等几秒后再查看。",
        "log_heading": "详细日志（遇到问题时可截图发给维护者）：",
        "no_logs": "（暂无日志）",
        "close": "关闭",
        "detection_failed": "未能自动检测网卡，请填写 Windows 中的 Wi-Fi 网卡名称。",
        "confirm_settings": "请确认账号、校园网络名称和 Wi-Fi 网卡。",
        "installed_follow_up": "安装完成。{summary}",
        "operation_failed": "操作失败",
        "retry": "操作失败，请检查填写的信息后重试。",
        "error_details": "{guidance}\n\n详细信息：\n{details}",
        "installed_pending": "安装完成，后台正在检查网络…稍后可点“查看运行状态”确认结果。",
        "installed_title": "安装完成",
        "installed_message": "开机自动登录已启用，以后开机会自动登录校园网。\n可以点“查看运行状态”确认是否登录成功。",
        "uninstalled": "已卸载。",
        "startup_failed": "无法启动安装程序",
        "admin_required": "需要管理员权限才能安装开机任务。请允许 Windows 权限提示后重试。",
        "command_failed": "安装程序运行失败。",
        "missing_asset": "发布包缺少 {name}，请重新下载完整安装程序。",
        "logged_in": "已自动登录校园网 {0}。",
        "online": "已连接校园网 {0}，当前在线，无需再次登录。",
        "login_failed": "登录失败：{0}。请检查账号和密码，然后重新安装。",
        "waiting": "当前没有连接校园网（现在的网络：{1}），连上 {0} 后会自动登录。",
        "network_failed": "暂时无法读取 Wi-Fi 状态：{0}",
        "credentials_unusable": "保存的账号密码不可用，请重新安装并填写账号密码。",
        "supervisor_failed": "后台程序出错：{0}。请重新运行安装程序修复。",
        "process_exited": "后台程序意外退出（代码 {0}），正在自动重启。",
        "task_absent": "后台任务没有安装，请点“安装 / 更新并启用”。",
        "task_stopped": "后台任务没有在运行，请重新运行安装程序或重启电脑。",
        "last_record": "最后一条记录：{summary}",
    },
    "en": {
        "window_title": "TLS Campus Wi-Fi Auto Login · {version}",
        "heading": "Campus Wi-Fi Auto Login",
        "introduction": "Enter your account and password, then install once. Campus Wi-Fi will sign in automatically at startup.",
        "user": "Campus account",
        "password": "Password",
        "network": "Campus network / SSID",
        "interface": "Wi-Fi adapter",
        "network_hint": "Use the campus Wi-Fi SSID or its Windows network profile name.",
        "install": "Install / Update and enable",
        "uninstall": "Uninstall",
        "view_status": "View status",
        "credential_notice": "Account and password file: {path}\nOnly SYSTEM and administrators can access it.",
        "detecting": "Detecting Wi-Fi adapters…",
        "ready": "Ready",
        "incomplete_title": "Missing information",
        "incomplete": "Enter your account, password, campus network name, and Wi-Fi adapter.",
        "installing": "Installing and starting the background task…",
        "uninstall_prompt": "Stop automatic login and remove the startup task.\n\nAlso delete saved credentials and logs?\n"
                            "· Yes: delete all saved data (recommended if you no longer use this app)\n"
                            "· No: stop the task and keep credentials\n· Cancel: do not uninstall",
        "uninstalling": "Stopping and removing the background task…",
        "reading_status": "Reading status…",
        "status_title": "Status",
        "task_state": "Background task: {state}",
        "state_running": "Running",
        "state_ready": "Installed but stopped (starts after a restart)",
        "state_disabled": "Disabled",
        "state_queued": "Queued",
        "state_unknown": "Unknown",
        "state_absent": "Not installed",
        "latest_result": "Latest result: {summary}",
        "no_records": "No records yet. Wait a few seconds and check again.",
        "log_heading": "Detailed logs (share a screenshot with the maintainer if needed):",
        "no_logs": "(No logs yet)",
        "close": "Close",
        "detection_failed": "Could not detect adapters. Enter the Wi-Fi adapter name shown in Windows.",
        "confirm_settings": "Check your account, campus network name, and Wi-Fi adapter.",
        "installed_follow_up": "Installation complete. {summary}",
        "operation_failed": "Operation failed",
        "retry": "The operation failed. Check your settings and try again.",
        "error_details": "{guidance}\n\nDetails:\n{details}",
        "installed_pending": "Installed. Checking the network… Select “View status” shortly to confirm the result.",
        "installed_title": "Installation complete",
        "installed_message": "Automatic login at startup is enabled.\nSelect “View status” to check whether login succeeded.",
        "uninstalled": "Uninstalled.",
        "startup_failed": "Cannot start setup",
        "admin_required": "Administrator permission is required to install the startup task. Allow the Windows permission prompt and try again.",
        "command_failed": "The installer failed.",
        "missing_asset": "The release is missing {name}. Download the complete installer again.",
        "logged_in": "Automatically signed in to campus network {0}.",
        "online": "Connected to campus network {0} and already online. No login needed.",
        "login_failed": "Login failed: {0}. Check your account and password, then reinstall.",
        "waiting": "Not connected to campus Wi-Fi (current network: {1}). Login will start when you connect to {0}.",
        "network_failed": "Could not read Wi-Fi status: {0}",
        "credentials_unusable": "Saved credentials are unusable. Reinstall and enter your account and password.",
        "supervisor_failed": "The background supervisor failed: {0}. Run setup again to repair it.",
        "process_exited": "The background process exited unexpectedly (code {0}) and is restarting automatically.",
        "task_absent": "The background task is not installed. Select “Install / Update and enable”.",
        "task_stopped": "The background task is stopped. Run setup again or restart your computer.",
        "last_record": "Last record: {summary}",
    },
}


def translate(key, language="zh-CN", *arguments, **values):
    return STRINGS[language][key].format(*arguments, **values)


def system_language():
    """Use the Windows display language, independent of regional formats."""
    if os.name == "nt":
        try:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetUserDefaultUILanguage.restype = ctypes.c_ushort
            # All Chinese Windows display-language variants use primary ID 4.
            return "zh-CN" if kernel.GetUserDefaultUILanguage() & 0x3FF == 4 else "en"
        except OSError:
            pass
    return "en"


def preferred_language():
    try:
        saved = json.loads(PREFERENCES.read_text(encoding="utf-8"))
        if isinstance(saved, dict) and saved.get("language") in LANGUAGES:
            return saved["language"]
    except (OSError, ValueError, TypeError):
        pass
    return system_language()


def save_language(language):
    if language not in LANGUAGES:
        raise ValueError("Unsupported setup language: %s" % language)
    try:
        PREFERENCES.parent.mkdir(parents=True, exist_ok=True)
        PREFERENCES.write_text(json.dumps({"language": language}), encoding="utf-8")
    except OSError:
        # A read-only profile must not stop the current language switch or setup.
        pass


class SetupError(OSError):
    """Keep an error translatable until the GUI displays the worker's result."""

    def __init__(self, key, **values):
        self.key, self.values = key, values
        super().__init__(translate(key, **values))

    def localize(self, language):
        return translate(self.key, language, **self.values)


def error_message(error, language):
    if isinstance(error, SetupError):
        return error.localize(language)
    return translate("error_details", language,
                     guidance=translate("retry", language), details=str(error))
