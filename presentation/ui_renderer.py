"""UI渲染器模块

负责创建和管理悬浮球（知时助手的常驻指示）的窗口，包括：
- 半透明显示窗口
- 右键菜单
- 气泡提示
- 位置控制与贴边吸附

使用 PySide6 实现跨平台窗口渲染。

注意：
    - 窗口使用 Qt.WA_TranslucentBackground 实现透明背景
    - 窗口无标题栏，支持拖拽移动
    - 支持 DPI 适配
"""

import sys

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QMenu,
    QGraphicsOpacityEffect, QMessageBox,
)
from PySide6.QtCore import Qt, QPoint, Signal, QObject
from PySide6.QtGui import QAction, QCursor, QGuiApplication

from event_bus import event_bus
from data.config_manager import config_manager
from data.log_manager import log_manager
from presentation.bubble import Bubble
from presentation.design import install as install_theme
from presentation.forms import DEFAULT_FORM, Form, build_form
from presentation.window_behavior import RaiseOnClickMixin


def _build_initial_form(name: str = None) -> Form:
    """按形态名建当前外观。

    2026-10-15 起球是唯一形态（桌宠与整套宠物模型资源已移除）。
    空值与旧配置里残留的形态名一律按默认（球）处理；`build_form` 对
    其它未知取值也会回退到球 —— 配置写错不该让窗口消失。
    """
    key = (name or "").strip().lower()
    if not key or key in ("pet", "petform"):
        key = DEFAULT_FORM
    return build_form(key, size=config_manager.get("appearance.orb_size", 52))


class ShellWindow(RaiseOnClickMixin, QWidget):
    """外壳窗口 —— 承载一切**形态无关**的行为。

    无边框 / 置顶 / 透明 / 拖拽 / 位置持久化 / 右键菜单 / 气泡 /
    关闭到托盘都住在这里；「长什么样」交给可替换的 `Form`（`forms.py`）。

    为什么保留 `ui_manager.window` 这个名字
        4 个插件拿它当对话框父窗口、`main.py` 拿它当动画落点 ——
        它是既有契约。换形态只换内胆，契约面不动（见 AGENTS.md §4.11）。
    """

    # 信号
    clicked = Signal(QPoint)
    dragged = Signal(QPoint)
    rightClicked = Signal(QPoint)

    def __init__(self, form: Form | None = None, parent=None):
        super().__init__(parent)

        # 窗口属性
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |       # 无边框
            Qt.WindowType.WindowStaysOnTopHint |     # 置顶
            Qt.WindowType.Tool                         # 工具窗口（不在任务栏显示）
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        # 拖拽支持
        self._drag_pos = None
        #: 贴边状态。`_snapped` = 当前贴在屏幕边缘（有一截在屏幕外）；
        #: `_edge_side` 记住贴的是哪一边，鼠标移开时要贴回去。
        self._snapped = False
        self._edge_side = None

        # 动画组件
        self._anim_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._anim_effect)

        # 透明度（从配置读取，限制在可见范围 0.3~1.0，防止配置过低导致看不见）
        self._opacity = max(0.3, min(1.0, float(config_manager.get("window.opacity", 0.9))))
        self.setWindowOpacity(self._opacity)

        # 气泡是**独立顶层窗口**（见 `presentation/bubble.py`）——
        # 球窗只有 64px，放窗口里会被裁掉。
        self._bubble = Bubble()

        # --- 内胆（外观）---
        # 窗口尺寸由形态决定，外壳不猜。首次 set_form 时还没有旧形态，
        # 所以按旧语义恢复左上角位置；之后再换形态就按**中心点**对齐。
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._form: Form | None = None
        self.set_form(form or _build_initial_form())

        self._restore_position()
        self._ensure_on_screen()

    # ----- 外观 -----

    def set_form(self, form: Form) -> None:
        """替换外观。

        窗口尺寸跟着形态走，**中心点保持不变** —— 形态尺寸变化时，
        如果按左上角对齐，窗口会往右下角飘掉一大截。
        """
        center = self._center() if self._form is not None else None

        if self._form is not None:
            self._layout.removeWidget(self._form)
            self._form.hide()
            self._form.setParent(None)
            self._form.deleteLater()

        self._form = form
        form.setParent(self)
        form.attach(self)
        self._layout.addWidget(form)
        self.setFixedSize(form.form_size())
        if center is not None:
            self._move_center(center)
        # 形态可以否决 `window.opacity` —— 球体自带半透明，再叠一层会糊
        opacity = form.preferred_opacity()
        if opacity is not None:
            self.setWindowOpacity(max(0.3, min(1.0, float(opacity))))
        form.show()

    def form(self) -> Form | None:
        """当前外观（测试与目检用）。"""
        return self._form

    def animation_target(self):
        """动画的落点。球没有精灵图，返回 None。"""
        return self._form.animation_target() if self._form is not None else None

    def wants_shell_motion(self) -> bool:
        """是否允许动画 `move()` 这个外壳窗口（转发给形态）。

        球返回 False —— 它是用户摆好、还会贴边的常驻指示，
        被数值动画挪走就会「拖完自己弹回去」。详见 `forms.Form`。
        """
        return self._form.wants_shell_motion() if self._form is not None else True

    def set_state(self, name: str) -> None:
        """状态机状态变化 —— 转发给形态。"""
        if self._form is not None:
            self._form.set_state(name)

    def _center(self) -> QPoint:
        return self.geometry().center()

    def _move_center(self, center: QPoint) -> None:
        """把**几何中心**移到 `center`。

        刻意不用「目标中心 ± 半个宽度」那种算法：无边框窗口在 Windows 上
        仍可能带 1px 的不可见边框，而 `move()` 作用在 frame 上 —— 直接算
        会累积漂移（实测换形态后差 1px）。改成「先求当前几何中心与目标的
        差值，再平移」，与 frame 无关，且自带校正。
        """
        self.move(self.pos() + center - self.geometry().center())

    def _restore_position(self) -> None:
        """恢复窗口位置。

        持久化的是**中心点**，不是左上角 —— 窗口尺寸由形态决定
        按左上角存的话，形态尺寸变了之后球会往
        右下角飘掉一大截（两者差 68px）。
        """
        center = config_manager.get("window.center")
        if isinstance(center, (list, tuple)) and len(center) == 2:
            self._move_center(QPoint(int(center[0]), int(center[1])))
            return
        # 迁移：老配置只有左上角 `window.position` + 固定边长 `window.size`，
        # 按旧尺寸换算成中心点（这样升级后位置不会跳）。
        position = config_manager.get("window.position", [100, 200])
        size = config_manager.get("window.size", [200, 200])
        if (isinstance(position, (list, tuple)) and len(position) == 2
                and isinstance(size, (list, tuple)) and len(size) == 2):
            self._move_center(QPoint(int(position[0]) + int(size[0]) // 2,
                                     int(position[1]) + int(size[1]) // 2))
            return
        self._move_center(QPoint(100 + self.width() // 2, 200 + self.height() // 2))

    def _remember_center(self) -> None:
        """把当前位置（中心点）写进配置，下次启动恢复。"""
        center = self._center()
        config_manager.set("window.center", [center.x(), center.y()])
        config_manager.save()

    # ----- 贴边 -----

    def _screen(self):
        """窗口当前所在的那块屏幕。

        必须按**窗口位置**取屏，不能用主屏 —— 多显示器下把窗口拖到第二块
        屏的边缘时，用主屏的可用区会把它吸到主屏的边上。
        """
        return (QGuiApplication.screenAt(self._center())
                or QGuiApplication.screenAt(self.pos())
                or QGuiApplication.primaryScreen())

    def _ensure_on_screen(self) -> None:
        """确保窗口落在某块屏幕里。

        分辨率改了 / 显示器拔了之后，老位置可能整个落在屏幕之外 ——
        那时用户既看不见也点不到，只能去手改配置文件。
        """
        if QGuiApplication.screenAt(self._center()) is not None:
            return
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        self._move_center(screen.availableGeometry().center())

    def _snap_to_edge(self) -> None:
        """吸附到最近的屏幕左 / 右边缘，并藏起一截。

        **只有真的靠近两侧才吸**（`Form.edge_snap_trigger()`）：原来无条件
        按「中心点在哪半屏」吸附，球在屏幕正中松手也会被拽到边上 ——
        用户摆好的位置被系统推翻，比不吸附更烦人。离两边都远时就地停住。

        不需要吸附的形态走这里也只是记一下位置。
        """
        form = self._form
        if form is None or not form.wants_edge_snap():
            self._remember_center()
            return
        screen = self._screen()
        if screen is None:
            self._remember_center()
            return

        avail = screen.availableGeometry()
        # 窗口左右边缘到屏幕边缘的距离。负数 = 已经越过边缘（拖出屏外）。
        gap_left = self.x() - avail.left()
        gap_right = avail.right() + 1 - (self.x() + self.width())
        trigger = max(0, int(form.edge_snap_trigger()))

        if gap_left > trigger and gap_right > trigger:
            # 离两侧都远 → 不吸附。同时**清掉吸附态**：否则从贴边拖到
            # 中间之后，鼠标一移开（`leaveEvent`）又会被拽回去。
            self._edge_side = None
            self._snapped = False
            self._remember_center()
            return

        inset = max(0, int(form.edge_snap_inset()))
        side = "left" if gap_left <= gap_right else "right"
        if side == "left":
            x = avail.left() - inset
        else:
            x = avail.right() + 1 - self.width() + inset
        y = max(avail.top(), min(self.y(), avail.bottom() - self.height() + 1))

        self._edge_side = side
        self._snapped = True
        self.move(x, y)
        self._remember_center()

    def _expand_from_edge(self) -> None:
        """从吸附态完全露出（仍然贴边，但不藏）。"""
        if not self._edge_side:
            return
        screen = self._screen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        if self._edge_side == "left":
            x = avail.left()
        else:
            x = avail.right() + 1 - self.width()
        self._snapped = False
        self.move(x, self.y())

    def enterEvent(self, event):
        """鼠标移入 → 从屏幕边缘完全露出。

        贴边时有一截藏在屏幕外（刻意少挡桌面），但用户想看清环 / 点它时，
        应该能完整看到。
        """
        if self._snapped:
            self._expand_from_edge()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标移出 → 贴回去（拖动过程中不贴，否则会跟用户抢位置）。"""
        if self._drag_pos is None and self._edge_side:
            self._snap_to_edge()
        super().leaveEvent(event)

    def is_snapped(self) -> bool:
        """当前是否贴在屏幕边缘（测试与目检用）。"""
        return self._snapped

    def edge_side(self):
        """贴的是哪一边："left" / "right" / None。"""
        return self._edge_side

    def show_text(self, text: str, duration: int = 3000) -> None:
        """在窗口上方弹一个气泡。

        气泡是**独立顶层窗口**（`presentation/bubble.py`）：球窗只有 64px，
        放窗口里会被裁掉。
        """
        self._bubble.show_text(text, self, duration)

    # ----- 鼠标事件 -----

    def _stop_animations(self) -> None:
        """用户按住窗口 → 停掉正在播的动画。

        数值动画（摇一摇 / 弹跳）是**按动画开始时的坐标**去 `move()` 的。
        用户动画中途拖动时，下一个 tick 会把窗口拽回原处
        （实测：拖到 (900,500)，动画结束后停在 (470,300)）。
        按住即停，位置控制权就交还给用户了 —— `_stop_numeric` 会把窗口
        放回它自己的起点，之后的拖动从干净状态开始。
        """
        controller = getattr(self._get_ui_manager(), "anim_controller", None)
        if controller is not None:
            controller.stop()

    def mousePressEvent(self, event):
        """鼠标按下"""
        # 先置顶：球与 AI 面板 / 对话框同处置顶层，点谁谁在前
        self.raise_to_front()
        self._stop_animations()
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.clicked.emit(event.globalPosition().toPoint())
            event_bus.publish("PET_CLICKED", {"x": event.globalPosition().x(), "y": event.globalPosition().y()})

        elif event.button() == Qt.MouseButton.RightButton:
            self.rightClicked.emit(event.globalPosition().toPoint())
            self._show_context_menu(event.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, event):
        """双击 → 打开控制中心。

        单击留给「戳一下」的轻反馈（发 `PET_CLICKED`，状态机进 interact 5 秒），
        打开主窗口这种重动作放双击 —— 这样单击**不必延迟 250ms 等判定**，
        点击手感不会变钝。代价是双击时会先戳一下，但那本来就是无副作用的反馈。
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_control_center()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        """鼠标拖动"""
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos:
            new_pos = event.globalPosition().toPoint() - self._drag_pos
            self.move(new_pos)
            # 气泡是独立窗口，不会跟着窗口自动走 —— 得显式通知
            self._bubble.follow(self)
            self.dragged.emit(new_pos)
            event_bus.publish("PET_DRAGGED", {"x": new_pos.x(), "y": new_pos.y()})

    def mouseReleaseEvent(self, event):
        """鼠标释放"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            # 松手 → 吸附到最近的屏幕边缘（靠近两侧才吸）
            self._snap_to_edge()

    def _show_context_menu(self, pos: QPoint):
        """显示右键菜单（菜单项来自插件系统）"""
        menu = QMenu(self)

        ui_mgr = self._get_ui_manager()
        if ui_mgr and ui_mgr.plugin_manager:
            actions = ui_mgr.plugin_manager.get_menu_actions()
            # 按 category 分组，不同组之间加分隔线
            last_cat = None
            for act in actions:
                if last_cat and act.category != last_cat:
                    menu.addSeparator()
                qact = QAction(act.name, self)
                # 包一层异常捕获+日志：windowed exe（console=False）下
                # 未捕获异常会被静默吞掉，表现为"点了没反应"
                qact.triggered.connect(
                    lambda checked=False, cb=act.callback, name=act.name: self._run_menu_action(name, cb)
                )
                menu.addAction(qact)
                last_cat = act.category
        else:
            # 后备：至少保留退出
            qact = QAction("退出", self)
            qact.triggered.connect(self._quit_app)
            menu.addAction(qact)

        menu.popup(QCursor.pos())

    def _open_control_center(self):
        """打开控制中心（主窗口）。"""
        try:
            from presentation.control_center import open_control_center

            ui_mgr = self._get_ui_manager()
            open_control_center(getattr(ui_mgr, "_pet_app", None))
        except Exception as e:  # noqa: BLE001
            import traceback

            log_manager.error(f"打开控制中心失败: {e}\n{traceback.format_exc()}")

    def _run_menu_action(self, name: str, callback):
        """执行插件菜单回调，异常记录日志而非静默吞掉"""
        try:
            callback()
        except Exception as e:
            import traceback
            log_manager.error(f"菜单项 [{name}] 执行失败: {e}\n{traceback.format_exc()}")
            # 延迟导入：dialogs 会拉起 tools/*，放在模块顶层会让启动期多背一截依赖
            from presentation.dialogs import message_box
            from PySide6.QtWidgets import QMessageBox
            message_box(self, QMessageBox.Icon.Warning, "插件错误",
                        f"菜单项 [{name}] 打开失败：\n{e}")

    def _quit_app(self):
        """退出应用"""
        QApplication.instance().quit()

    def closeEvent(self, event):
        """关闭拦截：默认最小化到托盘（配置 window.close_to_tray 控制）

        真正退出走托盘菜单/右键菜单的「退出」（app.stop → app.quit，
        quit 不会触发 closeEvent，不会递归）。
        """
        if config_manager.get("window.close_to_tray", True):
            event.ignore()
            self.hide()
            # 首次隐藏时气泡提示（托盘图标可能尚未就绪，容错）
            tray = getattr(self, "_tray_icon", None)
            if tray:
                tray.show_message("知时助手", "我藏到系统托盘里啦，双击托盘图标唤出我~")
        else:
            super().closeEvent(event)

    def _get_ui_manager(self):
        """获取UIManager实例"""
        return getattr(self, '_ui_manager', None)

    def set_window_opacity(self, opacity: float):
        """
        设置窗口透明度

        Args:
            opacity: 0.0 - 1.0
        """
        self._opacity = max(0.3, min(1.0, opacity))
        self.setWindowOpacity(self._opacity)


class UIManager(QObject):
    """UI管理器 - 管理整个表现层的UI"""

    # 跨线程安全信号：状态回调在事件发布者线程执行，UI 操作必须转回主线程
    _text_requested = Signal(str, int)
    #: 状态变化转发给当前形态。同样必须是**类体**里的信号（实例属性写法
    #: 拿到的是裸 Signal 对象，连 connect 都没有）—— 状态机的 `update()`
    #: 跑在 `PetDemo._setup_state_update` 的工作线程上。
    _state_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.app = None
        self.window = None
        self._initialized = False
        self.anim_controller = None
        self.plugin_manager = None  # 由 PluginManager 注入
        #: PetDemo 实例（由 main.py 注入）。控制中心需要它来读状态机 / 插件管理器。
        self._pet_app = None
        self._text_requested.connect(self._show_text_on_window)
        self._state_requested.connect(self._apply_state_on_window)

    def set_plugin_manager(self, pm):
        """注入插件管理器"""
        self.plugin_manager = pm

    def set_pet_app(self, pet_app):
        """注入 PetDemo 实例。"""
        self._pet_app = pet_app

    def open_control_center(self):
        """打开控制中心（主窗口）。"""
        from presentation.control_center import open_control_center

        return open_control_center(self._pet_app)

    def set_anim_controller(self, controller):
        """注入动画控制器"""
        self.anim_controller = controller
        # 连接 AnimController 的文字请求信号到外壳的 show_text()
        if controller and self.window:
            controller.text_requested.connect(
                lambda text, sec: self.window.show_text(text, int(sec * 1000))
            )
            self._sync_anim_target()

    def _sync_anim_target(self) -> None:
        """把「数值动画的目标控件」对齐到当前形态。

        数值动画（摇一摇 / 弹跳 / 缩放）是通过 `move()` / `setFixedSize()`
        作用在**外壳窗口**上的。这对「会自己动的角色」成立，对球不成立 ——
        球会被拽回拖动前的坐标、脱离贴边状态。
        所以由形态自己决定（`wants_shell_motion()`），这里只负责执行。
        """
        if not self.anim_controller or not self.window:
            return
        self.anim_controller.set_target_widget(
            self.window if self.window.wants_shell_motion() else None
        )

    def initialize(self):
        """初始化UI（必须在主线程中调用）"""
        if self._initialized:
            return

        # DPI 适配必须在 QApplication 创建之前设置才生效
        if QApplication.instance() is None:
            QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling)
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setApplicationName("ZhiShiAssistant")
        self.app.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

        # 装设计系统：Fusion 基样式 + QPalette + 全应用 QSS + 字体。
        #
        # 为什么必须是 Fusion
        #   只有 Fusion 在所有平台都完整支持 QSS。用 Windows 原生样式时
        #   UxTheme 会忽略大量 QSS 属性（圆角、hover、padding 直接失效），
        #   于是「统一样式」变成一句空话。
        #
        # 之后 `design.set_theme()` 会自动重装，窗口不需要各自处理换肤。
        install_theme(self.app)

        # 关掉「最后一个窗口关闭就退出」。
        #
        # 默认值是 True，而本项目两个**常驻**窗口（ShellWindow / AIPanel）都带
        # Qt.Tool 标志 —— Tool 窗口不计入「最后窗口」判定。于是任何一次
        # 普通 QDialog（AI 服务设置、番茄钟…）被关闭时，Qt 会认为
        # 「没有窗口了」→ 直接 quit，表现为「关掉设置界面，整个应用退出了」。
        #
        # 关闭该开关后，退出只能由显式调用 app.quit() 触发，共两处：
        #   · 托盘菜单 / 右键菜单「退出」→ main.PetDemo.stop() → app.quit()
        #   · ShellWindow._quit_app()（右键菜单直连）
        # 这样「关对话框」与「退应用」彻底解耦。
        #
        # 验证：spikes/s6_window_lifecycle.py（tool-default 复现 / tool-fixed 存活）
        self.app.setQuitOnLastWindowClosed(False)

        self.window = ShellWindow(_build_initial_form())
        self.window._ui_manager = self  # 让窗口能找到 UIManager

        # 注册事件监听
        self._setup_event_listeners()

        self._initialized = True

    def _setup_event_listeners(self):
        """设置事件监听器"""
        # 动画播放由 AnimController 通过事件总线独立处理，UIManager 只负责UI反馈
        event_bus.subscribe("REQUEST_SOUND", self._on_request_sound)
        event_bus.subscribe("STATE_CHANGE", self._on_state_change)

    def _on_state_change(self, event):
        """状态变更 → 显示气泡文字"""
        data = event.get("data", {})
        to_state = data.get("to", "")
        state_texts = {
            "focus":    "加油！我在陪你~",
            "relax":    "休息一下吧~",
            "sleep":    "我先睡会儿...",
            "interact": "嘿嘿！",
            "idle":     "我在看着你哦",
        }
        text = state_texts.get(to_state, "")
        if text:
            # 状态回调可能在非主线程执行，通过信号转回主线程操作 UI
            self._text_requested.emit(text, 2500)
        # 形态自己决定怎么表现这个状态（球换环与图标）。
        # 同样走信号 —— 状态机的 update() 跑在工作线程上。
        self._state_requested.emit(to_state)

    def _show_text_on_window(self, text: str, duration_ms: int):
        """在主线程显示气泡文字"""
        if self.window:
            self.window.show_text(text, duration_ms)

    def _apply_state_on_window(self, name: str):
        """在主线程把状态转给当前形态。"""
        if self.window:
            self.window.set_state(name)

    def show(self):
        """显示窗口"""
        if self.window:
            self.window.show()

    def run(self):
        """进入事件循环"""
        if self.app:
            self.app.exec()

    def _on_request_sound(self, event):
        """处理音效请求"""
        data = event.get("data", {})
        sound_type = data.get("type", "")
        print(f"播放音效: {sound_type}")


