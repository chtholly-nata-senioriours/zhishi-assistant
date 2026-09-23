# -*- coding: utf-8 -*-
"""GiWiFi 校园网自动登录插件

保持原版程序架构与逻辑：
- NetworkChecker(QThread) 轮询 check_online，断网发 login_needed(portal_url)
- 收到 login_needed 且配置了账号密码且开启 auto_login → 后台线程调用
  login_giwifi（与原版 MainWindow.auto_login 相同的调用方式）
- 登录结果通过 Qt Signal 回 UI 线程，仅更新插件自身对话框（若打开）

适配差异（不改逻辑，只改挂载方式）：
- 不再是独立 QApplication 主窗口，而是挂入桌宠右键菜单的一个入口
- 配置读写复用原版 config.load_config / save_config（路径已改 ~/.pet_demo）
- 日志复用原版 logger.log
"""
import sys
import threading
from pathlib import Path

# PluginManager 以单文件方式动态加载本插件（无包上下文），
# login_worker/network_checker/logger/config 之间使用平级绝对导入，
# 故把插件目录挂到 sys.path 以解析这些模块（对桌宠主程序无侵入，
# 模块名 giwifi_* 前缀风险低；logger/config 为插件私有名，加载时优先命中）。
_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from PySide6.QtCore import QObject, Signal, QThread

from extensions.base_plugin import BasePlugin, MenuAction
from config import load_config, save_config
from login_worker import login_giwifi, logout_giwifi, get_online_duration, check_online
from network_checker import NetworkChecker
from logger import log


class _UiBridge(QObject):
    """工作线程 → UI 线程 的信号桥（登录在下层裸线程中执行，需经 Qt Signal 跨线程）"""
    login_done = Signal(bool, str, object)
    logout_done = Signal(bool, str)


class GiwifiPlugin(BasePlugin):
    def on_load(self, app) -> bool:
        self._config = load_config()
        self._logout_url = None
        self._dialog = None
        self._bridge = _UiBridge()
        self._bridge.login_done.connect(self._on_login_done)
        self._bridge.logout_done.connect(self._on_logout_done)

        # 与原版一致的轮询线程：interval 取配置 check_interval
        self._checker = NetworkChecker(
            interval=self._config.get("check_interval", 10),
            config_portal_url=self._config.get("portal_url", ""),
        )
        self._checker.status_changed.connect(self._on_status_changed)
        self._checker.login_needed.connect(self._on_login_needed)
        self._checker.start()
        log("插件已加载，开始网络轮询")
        return True

    def on_unload(self):
        self._checker.stop()
        self._checker.wait(3000)
        log("插件已卸载，轮询停止")

    # ----- 菜单 -----
    def get_menu_actions(self):
        return [MenuAction("校园网", self._open_dialog, category="tools")]

    # ----- 状态/登录（与原版 MainWindow.auto_login / manual_login 逻辑一致）-----
    def _on_status_changed(self, online: bool):
        self._online = online
        if self._dialog is not None:
            self._dialog.set_online(online)

    def _on_login_needed(self, portal_url: str):
        """断网自动登录 —— 原版：有账号密码且开关开启才执行"""
        cfg = load_config()
        if not cfg.get("auto_login"):
            return
        if not cfg.get("username") or not cfg.get("password"):
            return
        log(f"检测到断网，自动登录 portal={portal_url}")
        self._start_login(cfg["username"], cfg["password"], portal_url)

    def _start_login(self, username, password, portal_url):
        """后台线程跑同步 login_giwifi，结果经 _bridge 回 UI 线程
        （与原版逻辑一致：登录函数本身不改，只是执行位置从 QThread.run
        改为守护线程，login_worker 内部使用全局 session，天然串行安全）"""
        threading.Thread(
            target=lambda: self._bridge.login_done.emit(*_call_login(username, password, portal_url)),
            daemon=True,
        ).start()

    def manual_login(self, username, password):
        """手动登录（对话框按钮触发）—— 原版 manual_login 同名语义"""
        portal_url = self._config.get("portal_url", "")
        self._start_login(username, password, portal_url)

    def manual_logout(self):
        """手动下线 —— 原版 manual_logout 同名语义"""
        if not self._logout_url:
            # 与原版一致：无 logout_url 时先在线检测刷新
            online, portal = check_online(timeout=5)
            if online:
                self._bridge.logout_done.emit(False, "当前未通过本插件登录，无法下线")
            else:
                self._bridge.logout_done.emit(False, "当前未联网")
            return
        threading.Thread(
            target=lambda: self._bridge.logout_done.emit(*_call_logout(self._logout_url)),
            daemon=True,
        ).start()

    def _on_login_done(self, ok: bool, msg: str, logout_url):
        if ok:
            self._logout_url = logout_url
            log(f"登录成功: {msg}")
        else:
            log(f"登录失败: {msg}")
        if self._dialog is not None:
            self._dialog.on_login_result(ok, msg)

    def _on_logout_done(self, ok: bool, msg: str):
        log(f"下线: {msg}")
        if ok:
            self._logout_url = None
        if self._dialog is not None:
            self._dialog.on_logout_result(ok, msg)

    # ----- 对话框 -----
    def _open_dialog(self):
        from giwifi_dialog import GiwifiDialog
        self._config = load_config()
        parent = self._find_window()
        self._dialog = GiwifiDialog(self, parent)
        self._dialog.set_online(getattr(self, "_online", None))
        self._dialog.exec()
        self._dialog = None

    def _find_window(self):
        if self.app and self.app.ui_manager and self.app.ui_manager.window:
            return self.app.ui_manager.window
        return None


def _call_login(username, password, portal_url):
    """在线程中执行同步 login_giwifi，返回 emit 所需参数元组"""
    ok, msg, logout_url = login_giwifi(username, password, portal_url)
    return ok, msg, logout_url


def _call_logout(logout_url):
    ok, msg = logout_giwifi(logout_url)
    return ok, msg
