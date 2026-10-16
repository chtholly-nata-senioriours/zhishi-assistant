# -*- coding: utf-8 -*-
"""系统托盘图标模块

QSystemTrayIcon 封装：
- 双击托盘：显示/隐藏悬浮球窗口
- 右键菜单：显隐悬浮球 + 插件菜单项（复用 PluginManager）+ 开机自启开关 + 退出
- 开机自启：读写 HKCU\\...\\Run 注册表（winreg，标准库，零新依赖）
- **常驻指示（P2.14）**：图标外圈画今日深度工作的进度环，悬停给精确数字

为什么进度画在「图标外圈」而不是换成纯进度环
    托盘图标在 16×16 上只有几十个像素。换成纯环就等于把这个指示弄丢了 ——
    用户在任务栏里认不出这是哪个程序。画在外圈（最外侧 3px 带）则两头都保住：
    中间的图标仍然可辨认，进度在任务栏底色上对比度最高。
    精确数字放在悬停提示里：16px 上写不下，也没必要。
"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QMessageBox
from PySide6.QtCore import QObject, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QAction

from data.config_manager import config_manager
from data.log_manager import log_manager

# 环状态判定与「白描边」与悬浮球**共用一份定义**（见 design/ring.py）——
# 两处画的是同一个「今日深度工作进度」（专注时同时改画「本次专注」），
# 各写各的迟早会漂。
from presentation.design.ring import (
    OUTLINE,
    STATE_ACTIVE,
    STATE_DONE,
    STATE_FOCUS,
    STATE_FOCUS_PAUSED,
    STATE_OFF,
    activity_state,
    ring_view,
)

#: 常驻指示多久刷一次。5 分钟太慢（用户盯着环等它动），1 秒太费
#: （每次都要查一次今天的记录）。60 秒是个「感觉得到在动」又不心疼的值。
PROGRESS_REFRESH_MS = 60_000

#: 专注计时进行中的刷新间隔。倒计时要看得出在走，60 秒一次显然不行；
#: 只在**专注进行中**才切到这个频率（平时仍是 60 秒）。
FOCUS_REFRESH_MS = 1_000

#: 托盘图标绘制画布尺寸 —— 高 DPI 下系统会放大取用，画小了会糊。
_ICON_CANVAS = 64

#: 环宽与描边。16px 时环宽约 1.8px —— 再细任务栏里就看不清了。
_RING_WIDTH = 7.0
_OUTLINE_EXTRA = 3.0

#: 托盘环的颜色 —— **刻意写死，不取主题色、也不进 `Palette`**。
#:
#: 为什么不能用主题色（S14 目检连踩两次）
#:     托盘图标画在**系统任务栏**上，底色由 Windows 决定，跟应用主题没关系。
#:       · `text_disabled` 在浅色主题下是 `#1F1F1F` —— 深色任务栏上**完全消失**；
#:       · `chart_track` 在浅色主题下是 `#DCDCDC` —— 深色任务栏上会被读成**满环**。
#:     而且「深色应用主题 + 浅色任务栏」这种组合下，取主题色怎么选都会有一半场景糊掉。
#:     所以这里用**固定色 + 一圈白描边**：白描边保证深色任务栏上有轮廓，
#:     深色底槽保证浅色任务栏上看得见环 —— 两边都不依赖任务栏的实际颜色。
_TRAY_OUTLINE = OUTLINE                      # 白描边（与球共用）
_TRAY_TRACK = QColor(0, 0, 0, 72)            # 底槽（半透明黑）
_TRAY_OFF = QColor(138, 138, 138)            # 关闭态：中性灰
_TRAY_PROGRESS = QColor(0, 103, 192)         # 进行中
_TRAY_DONE = QColor(16, 124, 16)             # 达成
#: 专注进行中 —— 琥珀色。为什么不用球的浅琥珀（#FFB04C）：
#: 任务栏底色不可控，浅色在浅色任务栏上会糊掉，这里取同一色系里更深的一档。
_TRAY_FOCUS = QColor(184, 106, 0)
#: 专注暂停 —— 同一色系去饱和，读出「停住了」而不是「换了一件事」。
_TRAY_FOCUS_PAUSED = QColor(150, 126, 96)


def activity_tooltip(progress: dict, focus: dict = None) -> str:
    """悬停提示 —— 精确数字在这里，不在图标上。

    `progress` 是插件 `focus_progress()` 的返回。
    `focus` 是**专注计时**的实况（`{"remaining": 秒, "paused": bool}`），
    不在专注时传 None。专注时它排在最前面：此刻用户最关心的是
    「还剩多久」，而不是今天累计了多少。
    """
    if focus:
        left = _mmss(focus.get("remaining") or 0)
        head = f"专注已暂停 · 还剩 {left}" if focus.get("paused") else f"专注中 · 还剩 {left}"
        if not progress.get("enabled"):
            return f"知时助手 · {head}"
        return f"知时助手 · {head}｜今日深度工作 {_hm(progress.get('focus') or 0.0)}"

    if not progress.get("enabled"):
        return "知时助手 · 行为记录已关闭（右键「今日概览」可开启）"
    focus_seconds = float(progress.get("focus") or 0.0)
    goal = float(progress.get("goal") or 0.0)
    if goal <= 0:
        return f"知时助手 · 今日深度工作 {_hm(focus_seconds)}"
    if focus_seconds >= goal:
        return (f"知时助手 · 今日深度工作 {_hm(focus_seconds)}"
                f"，已达成目标（{_hm(goal)}）")
    return (f"知时助手 · 今日深度工作 {_hm(focus_seconds)} / 目标 {_hm(goal)}"
            f"（{focus_seconds / goal * 100:.0f}%）")


def _mmss(seconds) -> str:
    """`12:05` —— 专注倒计时的格式，与番茄钟对话框一致。"""
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError):
        total = 0
    return f"{total // 60:02d}:{total % 60:02d}"


def _hm(seconds: float) -> str:
    """`1 小时 30 分` —— 托盘提示要短，所以自己算，不引 summary 的完整格式。"""
    minutes = max(0, int(round(float(seconds) / 60.0)))
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, rest = divmod(minutes, 60)
    return f"{hours} 小时 {rest} 分" if rest else f"{hours} 小时"


def progress_icon(ratio: float, state: str, base: QIcon = None) -> QIcon:
    """把进度环套在 `base` 图标外圈，返回新的 QIcon。

    `state == STATE_OFF` 时画**灰色整环**（表示「没在记录」），
    而不是一个空环（那会被读成「今天一点没干」）。
    """
    ratio = max(0.0, min(1.0, float(ratio)))
    px = QPixmap(_ICON_CANVAS, _ICON_CANVAS)
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    # 底图缩到环**内圈**里 —— 铺满画布的话环会压在图标边上，看着像被啃掉一圈
    inner = 46
    if base is not None and not base.isNull():
        pm = base.pixmap(QSize(inner, inner))
        if not pm.isNull():
            off = (_ICON_CANVAS - inner) // 2
            painter.drawPixmap(off, off, pm)

    rect = QRectF(5.5, 5.5, _ICON_CANVAS - 11.0, _ICON_CANVAS - 11.0)

    def _stroke(color, width: float) -> None:
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

    # ① 白描边（最外）→ 深色任务栏上靠它勾出轮廓
    _stroke(_TRAY_OUTLINE, _RING_WIDTH + _OUTLINE_EXTRA)
    painter.drawEllipse(rect)
    # ② 底槽 → 浅色任务栏上靠它看见环；深色任务栏上它自己融进底色也无妨
    _stroke(_TRAY_TRACK, _RING_WIDTH)
    painter.drawEllipse(rect)

    if state == STATE_OFF:
        _stroke(_TRAY_OFF, _RING_WIDTH)
        painter.drawEllipse(rect)
    elif ratio > 0.0:
        _stroke(_arc_color(state), _RING_WIDTH)
        # Qt 的角度单位是 1/16 度，0° 在 3 点钟方向 → 从 90°（12 点）
        # 起**顺时针**扫，才是「进度条长出来」的方向。
        painter.drawArc(rect, 90 * 16, -int(round(360 * 16 * ratio)))
    painter.end()
    return QIcon(px)


def _arc_color(state: str) -> QColor:
    """进度弧的颜色 —— 与悬浮球的 `_arc_color` 是同一套语义（见 ring.py）。"""
    if state == STATE_FOCUS:
        return _TRAY_FOCUS
    if state == STATE_FOCUS_PAUSED:
        return _TRAY_FOCUS_PAUSED
    return _TRAY_DONE if state == STATE_DONE else _TRAY_PROGRESS


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

        self._base_icon = QIcon()
        if icon_path and Path(icon_path).exists():
            self._base_icon = QIcon(icon_path)
            self._tray.setIcon(self._base_icon)

        self._tray.setToolTip("知时助手")
        self._tray.activated.connect(self._on_activated)

        self._build_menu()
        self._tray.show()

        # ----- 常驻指示（P2.14）-----
        # 换主题要重画（环的颜色来自 token）；插件不存在就整块跳过，
        # 保持原来的静态图标。
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(PROGRESS_REFRESH_MS)
        self._progress_timer.timeout.connect(self.refresh_activity)
        # 专注进行中时切到 1 秒（见 FOCUS_REFRESH_MS）—— 由 refresh_activity
        # 自己开关，不在别处维护「现在是不是在专注」这个状态。
        self._focus_timer = QTimer(self)
        self._focus_timer.setInterval(FOCUS_REFRESH_MS)
        self._focus_timer.timeout.connect(self.refresh_activity)
        try:
            from presentation.design.theme import theme

            theme().changed.connect(self.refresh_activity)
        except Exception as e:  # noqa: BLE001 —— 主题没装上也不该拖垮托盘
            log_manager.warning(f"托盘订阅主题变化失败: {e}")
        self.refresh_activity()

    # ----- 常驻指示 -----

    def _activity_plugin(self):
        pm = getattr(self._app, "plugin_manager", None) if self._app else None
        if pm is None:
            return None
        try:
            return pm.get_plugin("activity_advisor")
        except Exception:  # noqa: BLE001 —— 插件系统出问题不该影响托盘
            return None

    def _focus_snapshot(self) -> dict:
        """读番茄钟实况。不在专注时返回空 dict（**不是**「进度 0」）。

        任何异常都当「不在专注」处理 —— 计时器是个可选插件，
        它坏了不该让托盘图标消失。
        """
        timer = getattr(self._app, "timer", None) if self._app else None
        if timer is None:
            return {}
        try:
            status = timer.get_status()
        except Exception:  # noqa: BLE001
            return {}
        state = str(status.get("state") or "")
        if state not in ("running", "paused"):
            return {}
        return {
            "ratio": status.get("progress", 0.0),
            "remaining": status.get("remaining", 0),
            "paused": state == "paused",
        }

    def refresh_activity(self) -> None:
        """刷新托盘图标上的进度环与悬停提示。

        查库在**主线程**上做（一次 `segments_since` + 求和，今天最多几百行）。
        不为此起工作线程：环的刷新间隔是 60 秒，这点开销远小于
        「为一个小查询维护一套线程 + 信号」的复杂度。
        但**必须**兜住异常 —— 托盘图标画不出来就静默降级成静态图标，
        不能让一个可选的常驻指示把整个程序带崩。
        """
        plugin = self._activity_plugin()
        if plugin is None or not hasattr(plugin, "focus_progress"):
            return
        try:
            progress = plugin.focus_progress(1)
        except Exception as e:  # noqa: BLE001
            log_manager.warning(f"读取今日深度工作进度失败: {e}")
            return

        # 专注进行中 → 环改画**本次专注**。判定与球共用 `ring_view`：
        # 两处同时画着不同的量，用户会看到两个互相矛盾的环。
        focus = self._focus_snapshot()
        state, ratio = ring_view(
            enabled=progress.get("enabled", False),
            ratio=progress.get("ratio", 0.0),
            focus_ratio=focus.get("ratio") if focus else None,
            focus_paused=bool(focus.get("paused")),
        )
        self._tray.setIcon(progress_icon(ratio, state, self._base_icon))
        self._tray.setToolTip(activity_tooltip(progress, focus or None))

        if not self._progress_timer.isActive():
            self._progress_timer.start()
        # 专注时用 1 秒的节奏（倒计时要动），结束后立刻退回 60 秒
        if focus:
            if not self._focus_timer.isActive():
                self._focus_timer.start()
        elif self._focus_timer.isActive():
            self._focus_timer.stop()

    # ----- 菜单 -----

    def _build_menu(self):
        menu = QMenu()

        act_toggle = QAction("显示 / 隐藏悬浮球", menu)
        act_toggle.triggered.connect(self.toggle_pet)
        menu.addAction(act_toggle)

        menu.addSeparator()

        # 复用插件菜单项（与悬浮球右键菜单统一）
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
            # 延迟导入：dialogs 反过来 import 本模块，模块顶层导入会成环
            from presentation.dialogs import message_box
            message_box(None, QMessageBox.Icon.Warning, "插件错误",
                        f"菜单项 [{name}] 执行失败：\n{e}")

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
        # 双击托盘：显示/隐藏悬浮球
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_pet()

    def toggle_pet(self):
        """显示/隐藏悬浮球窗口"""
        window = self._get_window()
        if window is None:
            return
        if window.isVisible():
            window.hide()
        else:
            window.show()
            window.activateWindow()

    def open_control_center(self):
        """打开控制中心（主窗口）。"""
        try:
            from presentation.control_center import open_control_center

            open_control_center(self._app)
        except Exception as e:  # noqa: BLE001 —— 打不开也必须留下痕迹
            import traceback

            log_manager.error(f"托盘打开控制中心失败: {e}\n{traceback.format_exc()}")

    def _get_window(self):
        ui = getattr(self._app, "ui_manager", None) if self._app else None
        return getattr(ui, "window", None) if ui else None

    def show_message(self, title: str, body: str, timeout_ms: int = 2500):
        """托盘气泡通知"""
        self._tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information,
                               timeout_ms)

    def hide(self):
        """退出前隐藏托盘图标（否则图标残留到鼠标划过）"""
        try:
            self._progress_timer.stop()
        except Exception:  # noqa: BLE001
            pass
        self._tray.hide()
