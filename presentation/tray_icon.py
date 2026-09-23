# -*- coding: utf-8 -*-
"""系统托盘图标模块

QSystemTrayIcon 封装：
- 双击托盘：显示/隐藏桌宠窗口切换
- 右键菜单：显隐桌宠 + 插件菜单项（复用 PluginManager）+ 开机自启开关 + 退出
- 开机自启：读写 HKCU\\...\\Run 注册表（winreg，标准库，零新依赖）
"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QMessageBox
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon, QAction

from data.config_manager import config_manager
from data.log_manager import log_manager


# ═══════════════════════════════════════════════════════
#  开机自启动（Windows 注册表 HKCU Run）
# ═══════════════════════════════════════════════════════

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE_NAME = "PetDemo"


def is_autostart_enabled() -> bool:
    """读注册表实况（而非配置文件，避免用户手动删除后开关显示错误）"""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _RUN_VALUE_NAME)
            return True
    except (FileNotFoundError, OSError):
        return False
    except ImportError:
        return False


def set_autostart(enabled: bool) -> bool:
    """增删 HKCU Run 注册表项；自启命令带 --minimized 参数（静默进托盘）"""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                exe = Path(sys.executable)
                # 打包环境：exe 自身；源码环境：pythonw main.py --minimized
                if exe.name.lower() in ("pythonw.exe", "python.exe"):
                    main_py = Path(__file__).resolve().parents[1] / "main.py"
                    command = f'"{exe.with_name("pythonw.exe")}" "{main_py}" --minimized'
                else:
                    command = f'"{exe}" --minimized'
                winreg.SetValueEx(key, _RUN_VALUE_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, _RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
        log_manager.info(f"开机自启已{'开启' if enabled else '关闭'}")
        return True
    except OSError as e:
        log_manager.error(f"设置开机自启失败: {e}")
        return False


# ═══════════════════════════════════════════════════════
#  托盘图标
# ═══════════════════════════════════════════════════════

class TrayIcon(QObject):
    """系统托盘图标"""

    # 请求退出应用（由 main.py / PetDemo 接管真正的清理流程）
    quit_requested = Signal()

    def __init__(self, app=None, icon_path: str = None):
        super().__init__()
        self._app = app  # PetDemo 实例
        self._tray = QSystemTrayIcon()

        if icon_path and Path(icon_path).exists():
            self._tray.setIcon(QIcon(icon_path))

        self._tray.setToolTip("小小桌宠")
        self._tray.activated.connect(self._on_activated)

        self._build_menu()
        self._tray.show()

    # ----- 菜单 -----

    def _build_menu(self):
        menu = QMenu()

        act_toggle = QAction("显示 / 隐藏桌宠", menu)
        act_toggle.triggered.connect(self.toggle_pet)
        menu.addAction(act_toggle)

        menu.addSeparator()

        # 复用插件菜单项（与桌宠右键菜单统一）
        pm = getattr(self._app, "plugin_manager", None) if self._app else None
        if pm:
            for act in pm.get_menu_actions():
                qact = QAction(act.name, menu)
                qact.triggered.connect(
                    lambda checked=False, cb=act.callback, name=act.name: self._run_action(name, cb)
                )
                menu.addAction(qact)
            menu.addSeparator()

        # 开机自启开关（勾选态读注册表实况）
        self._act_autostart = QAction("开机自启动", menu)
        self._act_autostart.setCheckable(True)
        self._act_autostart.setChecked(is_autostart_enabled())
        self._act_autostart.triggered.connect(self._on_toggle_autostart)
        menu.addAction(self._act_autostart)

        menu.addSeparator()

        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(self.quit_requested.emit)
        menu.addAction(act_quit)

        self._tray.setContextMenu(menu)

    def _run_action(self, name: str, callback):
        """执行插件回调，异常记录日志（windowed exe 下防静默失败）"""
        try:
            callback()
        except Exception as e:
            import traceback
            log_manager.error(f"托盘菜单项 [{name}] 执行失败: {e}\n{traceback.format_exc()}")
            QMessageBox.warning(None, "插件错误", f"菜单项 [{name}] 执行失败：\n{e}")

    def _on_toggle_autostart(self, checked: bool):
        if set_autostart(checked):
            self._act_autostart.setChecked(checked)
            self.show_message("开机自启", "已开启，开机后将静默启动到托盘" if checked
                              else "已关闭")
        else:
            # 写注册表失败（非 Windows/权限问题），回滚勾选态
            self._act_autostart.setChecked(not checked)
            self.show_message("开机自启", "设置失败（仅支持 Windows）")

    # ----- 交互 -----

    def _on_activated(self, reason):
        # 双击托盘：显示/隐藏桌宠
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_pet()

    def toggle_pet(self):
        """显示/隐藏桌宠窗口"""
        window = self._get_window()
        if window is None:
            return
        if window.isVisible():
            window.hide()
        else:
            window.show()
            window.activateWindow()

    def _get_window(self):
        ui = getattr(self._app, "ui_manager", None) if self._app else None
        return getattr(ui, "window", None) if ui else None

    def show_message(self, title: str, body: str, timeout_ms: int = 2500):
        """托盘气泡通知"""
        self._tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information,
                               timeout_ms)

    def hide(self):
        """退出前隐藏托盘图标（否则图标残留到鼠标划过）"""
        self._tray.hide()
