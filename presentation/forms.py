# -*- coding: utf-8 -*-
"""外观（Form）—— 外壳里那块「可替换的内胆」。

背景
    原来 `PetWindow` 一个类同时干三件事：窗口行为、精灵图渲染、气泡。
    把常态外观从桌宠换成悬浮球时，**只有「精灵图渲染」这一件是形态相关的** ——
    另外两件（拖拽 / 置顶 / 位置 / 菜单 / 气泡 / 关闭到托盘）与形态无关。
    于是拆成 `ShellWindow`（外壳，形态无关）+ `Form`（外观，可替换）。
    2026-10-15 起桌宠形态与整套宠物模型资源已移除，**球是唯一形态**；
    但 `Form` 协议保留 —— 它是「外壳不关心外观长什么样」这条边界的载体。

Form 协议只有四个问题
    animation_target()   精灵图动画往哪画？没有精灵图的形态返回 None
    set_state(name)      状态机的状态怎么表现？球换环与图标
    form_size()          这个形态需要多大的窗口？
    wants_edge_snap()    松手后要不要吸附到屏幕边缘？

为什么要 form_size()
    窗口尺寸由形态决定，外壳不猜。调用方只说要哪种形态，不必关心尺寸。

为什么要 set_state() 而不是让状态机直接操作控件
    状态机不该知道外面长什么样。它只发 `STATE_CHANGE`，外壳转发给
    当前形态，形态自己决定用什么介质表达 —— 球用的是颜色 / 环 / 中心图标。
"""
from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QWidget

from presentation.design import icons
from presentation.design.ring import (
    STATE_DONE,
    STATE_FOCUS,
    STATE_FOCUS_PAUSED,
    STATE_OFF,
    ring_view,
)


class Form(QWidget):
    """外观基类。

    子类至少要实现 `form_size()`。其余钩子都有「什么都不做」的默认值 ——
    一个只静态显示、不参与动画与状态的外观不需要实现它们。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shell = None

    def attach(self, shell) -> None:
        """外壳把自己交给形态。

        形态需要 app / 插件管理器时从这里拿 —— 球要靠它读今日进度，
        但形态不该自己去 `QApplication.instance()` 里翻。
        """
        self._shell = shell

    def animation_target(self) -> QLabel | None:
        """精灵图动画的落点。没有精灵图的形态返回 None。

        `main.py` 拿到 None 时不给 `AnimController` 设图片目标（不换图）。
        注意这**不**代表「窗口可以不动」—— 那是 `wants_shell_motion()` 的事。
        """
        return None
    def wants_shell_motion(self) -> bool:
        """是否允许动画 `move()` 整个外壳窗口。

        数值动画（`wave` 摇一摇 / `happy` 弹跳 / `thumbs_up` 缩放）是通过
        `widget.move()` 作用在**外壳**上的。这对「会自己动的角色」成立，
        对「用户摆好位置的悬浮球」是灾难 —— 实测（`_probe_stale.py`）：

          · 动画把开始时的坐标存成 `original_pos`，之后每个 tick 都按它
            `move()`。用户动画中途把球拖走，下一 tick 就把球**拽回原处**
            （复现：拖到 (900,500)，动画结束后停在 (470,300)）。
          · 球贴边时是「故意藏 1/3」的，被动画一挪就脱离边缘。

        球的状态已经由环 / 图标 / 压暗表达（`set_state`），外加悬停放大与
        点击脉冲（都在窗口内完成），不需要也不应该让窗口位移。
        """
        return True

    def set_state(self, name: str) -> None:
        """状态机状态变化 —— 球换环与图标。"""

    def form_size(self) -> QSize:
        """这个形态需要的窗口尺寸（逻辑像素）。"""
        raise NotImplementedError

    def wants_edge_snap(self) -> bool:
        """松手后是否吸附到屏幕边缘。"""
        return False

    def edge_snap_inset(self) -> int:
        """贴边时有多少像素留在屏幕外（0 = 完全露出）。

        留一截在外面是为了少挡桌面 —— 但鼠标移上去外壳会把它完全拉出来。
        """
        return 0

    def edge_snap_trigger(self) -> int:
        """离屏幕左 / 右边缘多少像素以内才吸附（0 = 永不吸附）。

        为什么需要它
            原来的实现是「松手就按中心点在哪半屏吸附」—— 球在屏幕正中
            松手也会被拽到边上。用户摆的位置被系统推翻，比不吸附更烦人。
            所以改成**只有真的靠近两侧才吸**，中间区域随便停。
        """
        return 0

    def preferred_opacity(self) -> float | None:
        """形态自己希望的不透明度。None = 用 `window.opacity` 配置。

        球体本身已经带半透明（`_ORB_FILL` 的 alpha），再叠一层窗口级
        透明度会让它在深色壁纸上糊成一片，所以球返回 1.0。
        """
        return None

    def on_theme_changed(self) -> None:
        """应用主题变了 —— 自绘形态需要重取颜色并 update()。"""


# ---------------------------------------------------------------- 悬浮球

#: 悬浮球几何。窗口比球体大一圈 —— 留出描边与「被戳时弹一下」的余量，
#: 否则放大到 1.18 会被窗口裁掉。
_ORB_CANVAS_PAD = 12
_ORB_RING_INSET = 5.5        # 环中心线离球体外沿的距离
_ORB_RING_WIDTH = 5.0
_ORB_EDGE_WIDTH = 1.5
_HOVER_SCALE = 1.08

#: 球体配色 —— 与托盘环同一个理由（见 `design/ring.py`）：
#: 这次底色是**壁纸**，比任务栏更不可预测，所以固定色 + 白描边。
_ORB_FILL = QColor(28, 28, 28, 205)
_ORB_FILL_DIM = QColor(28, 28, 28, 135)      # 休眠
_ORB_EDGE = QColor(255, 255, 255, 235)
_ORB_TRACK = QColor(255, 255, 255, 58)
_ORB_OFF = QColor(255, 255, 255, 120)
_ORB_PROGRESS = QColor(76, 194, 255)         # #4CC2FF
_ORB_DONE = QColor(108, 203, 95)             # #6CCB5F
#: 专注计时进行中 —— 琥珀色。与蓝（今日进度）、绿（已达成）都拉得开，
#: 一眼就能看出「环现在说的是另一件事」。
_ORB_FOCUS = QColor(255, 176, 76)            # #FFB04C
#: 专注暂停 —— 同一个量的「停住了」态，靠透明度压暗，不换色
#: （换色会被读成第三种状态，而它其实只是暂停）。
_ORB_FOCUS_PAUSED = QColor(255, 176, 76, 110)

#: 状态 → 中心图标。状态机只有这几种状态，球用几个图标把它们标出来 ——
#: 这正是 `Form.set_state()` 存在的理由：状态机不该知道外面是什么形态。
_STATE_ICON = {
    "idle": "paw",
    "relax": "paw",
    "interact": "paw",
    "focus": "rocket",
    "sleep": "moon",
}

#: 进度刷新间隔，与托盘图标同值（`tray_icon.PROGRESS_REFRESH_MS`）。
_ORB_REFRESH_MS = 60_000

#: 专注态的轮询间隔。专注倒计时要**看得出在走**，60 秒一次显然不行；
#: 1 秒一次只是读几个属性，且**只有变化时才重绘**（见 `refresh_focus`）。
_ORB_FOCUS_MS = 1_000

#: 离屏幕左 / 右边缘多少像素以内才吸附。
#: 球窗 64px 宽，48 ≈ 大半个球 —— 拖到「明显贴边」时才吸，中间区域随便停。
_ORB_SNAP_TRIGGER = 48


class OrbForm(Form):
    """悬浮球 —— 常态外观。

    球体 + 球内进度环 + 中心图标。四态：常态 / 专注中 / 已达成 / 休眠。

    为什么是「球 + 环」而不是纯球
        环表达的是「今日深度工作进度」—— 与托盘图标是**同一个量**
        （状态判定共用 `design/ring.py`）。做成纯球的话，桌面上的常驻
        指示就只剩托盘那 16px 了，而球有 3 倍多的面积可用。

    单击为什么不做「打开窗口」
        单击发 `PET_CLICKED`（状态机进 interact 5 秒），球弹一下 + 冒气泡。
        打开控制中心放**双击** —— 单击就不必延迟 250ms 等双击判定，
        点击手感不会变钝。
    """

    def __init__(self, size: int = 52, parent=None):
        super().__init__(parent)
        self._diameter = max(32, int(size))
        self._canvas = self._diameter + _ORB_CANVAS_PAD
        self.setFixedSize(self._canvas, self._canvas)

        self._hover = False
        self._pulse = 1.0
        self._state = "idle"
        self._ratio = 0.0
        #: 采集开关。初值 False = 「还不知道在不在记录」→ 画中性灰整环，
        #: 等 `refresh_progress()` 拿到插件实况再改（与 P2.14 的约定一致：
        #: 空环会被读成「今天一点没干」，而真相是「还不知道」）。
        self._enabled = False
        self._ring_state = STATE_OFF
        self._ring_value = 0.0
        #: 专注计时：None = 不在专注（环回到「今日进度」语义）
        self._focus_ratio = None
        self._focus_paused = False
        self._sync_ring()

        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(_ORB_REFRESH_MS)
        self._progress_timer.timeout.connect(self.refresh_progress)

        self._focus_timer = QTimer(self)
        self._focus_timer.setInterval(_ORB_FOCUS_MS)
        self._focus_timer.timeout.connect(self.refresh_focus)

    # ----- Form 协议 -----

    def form_size(self) -> QSize:
        return QSize(self._canvas, self._canvas)

    def wants_shell_motion(self) -> bool:
        # 球是用户摆好的常驻指示，还要贴边 —— 动画一挪就散了（详见基类注释）。
        # 「弹一下」由球自己的 `_bounce()` 在窗口内完成，不靠移动窗口。
        return False

    def set_state(self, name: str) -> None:
        if name == self._state:
            return
        self._state = name
        if name == "interact":
            self._bounce()
        self.update()

    def preferred_opacity(self) -> float:
        # 球体自带半透明，不要再叠窗口级透明度
        return 1.0

    def wants_edge_snap(self) -> bool:
        # 球是常驻指示，停在工作区中间的话，用户每拖一次窗口都要绕开它
        return True

    def edge_snap_inset(self) -> int:
        # 约 1/3 藏在屏幕外，剩下的够点、也够看清环
        return self._canvas // 3

    def edge_snap_trigger(self) -> int:
        return _ORB_SNAP_TRIGGER

    def attach(self, shell) -> None:
        super().attach(shell)
        # 外壳就位后才谈得上读进度（要 app → plugin_manager）
        self.refresh_progress()
        self.refresh_focus()
        if not self._progress_timer.isActive():
            self._progress_timer.start()
        if not self._focus_timer.isActive():
            self._focus_timer.start()

    # ----- 进度 -----

    def refresh_progress(self) -> None:
        """从活动插件读今日进度并重绘。

        与托盘图标同一个数据源、同一套降级策略：插件缺失 / 查库抛异常
        → **静默保持现状**，不让一个可选的常驻指示把程序带崩。
        """
        plugin = self._activity_plugin()
        if plugin is None or not hasattr(plugin, "focus_progress"):
            return
        try:
            progress = plugin.focus_progress(1)
        except Exception:  # noqa: BLE001
            return
        self.set_progress(progress.get("ratio", 0.0), progress.get("enabled", False))

    def refresh_focus(self) -> None:
        """读番茄钟实况，决定环要不要改画「本次专注」。

        与 `refresh_progress` 一样：**任何异常都静默保持现状**。
        计时器是个可选插件（`app.timer`），它不在不该把球画崩。
        """
        try:
            timer = self._timer()
            if timer is None:
                self.set_focus(None)
                return
            status = timer.get_status()
        except Exception:  # noqa: BLE001
            # 连「拿计时器」这一步都兜住 —— 上面那句「任何异常都静默保持现状」
            # 要字面成立，否则将来 `_timer()` 多一层跳转就会变成崩溃点。
            return
        state = str(status.get("state") or "")
        if state in ("running", "paused"):
            self.set_focus(status.get("progress", 0.0), paused=(state == "paused"))
        else:
            self.set_focus(None)

    def set_focus(self, ratio, paused: bool = False) -> None:
        """设置专注态。`ratio=None` 表示不在专注。

        测试与目检直接调它，不必搭一个真计时器。
        """
        new_ratio = None if ratio is None else max(0.0, min(1.0, float(ratio)))
        changed = (new_ratio != self._focus_ratio
                   or bool(paused) != self._focus_paused)
        self._focus_ratio = new_ratio
        self._focus_paused = bool(paused) if new_ratio is not None else False
        self._sync_ring()
        # 1 秒轮询：**没变化就不重绘** —— 否则球每秒都在无谓重画一次
        if changed:
            self.update()

    def focus(self) -> tuple:
        """`(专注进度或 None, 是否暂停)` —— 只读，供测试与目检断言。"""
        return self._focus_ratio, self._focus_paused

    def set_progress(self, ratio: float, enabled: bool = True) -> None:
        """设置今日进度（0–1）。测试与目检直接调它，不必搭插件。"""
        self._ratio = max(0.0, min(1.0, float(ratio)))
        self._enabled = bool(enabled)
        self._sync_ring()
        self.update()

    def _sync_ring(self) -> None:
        """把「今日进度 + 专注态」合成环最终该画的样子（共用判定见 ring.py）。"""
        self._ring_state, self._ring_value = ring_view(
            enabled=self._enabled,
            ratio=self._ratio,
            focus_ratio=self._focus_ratio,
            focus_paused=self._focus_paused,
        )

    def progress(self) -> tuple:
        """(进度, 环状态) —— 只读，供测试与目检断言。

        专注进行中时这里返回的是**本次专注**的进度与 `focus` 态，
        因为那正是环此刻表达的东西。
        """
        return self._ring_value, self._ring_state

    def _activity_plugin(self):
        mgr = getattr(self._shell, "_ui_manager", None)
        app = getattr(mgr, "_pet_app", None)
        pm = getattr(app, "plugin_manager", None)
        if pm is None:
            return None
        try:
            return pm.get_plugin("activity_advisor")
        except Exception:  # noqa: BLE001
            return None

    def _timer(self):
        """番茄钟实例（挂在 `app.timer` 上）。插件没加载时返回 None。"""
        mgr = getattr(self._shell, "_ui_manager", None)
        app = getattr(mgr, "_pet_app", None)
        return getattr(app, "timer", None)

    # ----- 交互 -----

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def is_hovered(self) -> bool:
        return self._hover

    def _bounce(self) -> None:
        """被戳时弹一下。

        精灵图形态播 wave 动画，球没有帧资源 —— 用缩放脉冲代替，
        同样是「戳了有反应」的感觉。
        """
        anim = QVariantAnimation(self)
        anim.setDuration(340)
        anim.setStartValue(1.0)
        anim.setKeyValueAt(0.35, 1.18)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._on_pulse)
        anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _on_pulse(self, value) -> None:
        self._pulse = float(value)
        self.update()

    def pulse(self) -> float:
        return self._pulse

    # ----- 绘制 -----

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        scale = self._pulse * (_HOVER_SCALE if self._hover else 1.0)
        radius = self._diameter / 2.0 * scale

        # 1) 球体 —— 深色半透明底 + 一圈白描边
        p.setPen(QPen(_ORB_EDGE, _ORB_EDGE_WIDTH))
        p.setBrush(_ORB_FILL_DIM if self._state == "sleep" else _ORB_FILL)
        p.drawEllipse(center, radius, radius)

        # 2) 进度环（球体内侧靠边）
        ring_r = radius - _ORB_RING_INSET * scale
        rect = QRectF(center.x() - ring_r, center.y() - ring_r, ring_r * 2, ring_r * 2)
        pen = QPen(_ORB_TRACK, _ORB_RING_WIDTH * scale)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)

        if self._ring_state == STATE_OFF:
            # 「没在记录」画成灰色整环，不画空环 —— 空环会被读成「今天一点没干」
            pen.setColor(_ORB_OFF)
            p.setPen(pen)
            p.drawEllipse(rect)
        elif self._ring_value > 0.0:
            pen.setColor(self._arc_color())
            p.setPen(pen)
            # 12 点起、顺时针。角度单位是 1/16 度，所以两端都要 ×16。
            # ratio 已在 set_progress/set_focus 里夹到 [0,1] —— 不夹的话
            # int() 参数会溢出（见 AGENTS.md §4.9 的托盘环同类问题）。
            p.drawArc(rect, 90 * 16, -int(round(360 * 16 * self._ring_value)))

        # 3) 中心图标
        icon_name = self._icon_name()
        icon_size = max(12, int(radius * 0.82))
        dpr = self.devicePixelRatioF()
        pm = icons.pixmap(icon_name, "#FFFFFF", icon_size, dpr=dpr)
        target = QRectF(0.0, 0.0, float(icon_size), float(icon_size))
        target.moveCenter(center)
        p.setOpacity(0.55 if self._state == "sleep" else 1.0)
        p.drawPixmap(target, pm, QRectF(pm.rect()))
        p.setOpacity(1.0)
        p.end()

    def _arc_color(self) -> QColor:
        """进度弧的颜色由环**此刻在说什么**决定（专注 > 达成 > 进行中）。"""
        if self._ring_state == STATE_FOCUS:
            return _ORB_FOCUS
        if self._ring_state == STATE_FOCUS_PAUSED:
            return _ORB_FOCUS_PAUSED
        return _ORB_DONE if self._ring_state == STATE_DONE else _ORB_PROGRESS

    def _icon_name(self) -> str:
        """中心图标。

        专注态优先于「已达成」—— 专注进行中时画一个对勾（今日目标达成）
        会让人以为**这次专注**完成了，而它其实还在跑。
        """
        if self._ring_state == STATE_FOCUS_PAUSED:
            return "pause"
        if self._ring_state == STATE_FOCUS:
            return "clock"
        if self._ring_state == STATE_DONE:
            return "check"
        return _STATE_ICON.get(self._state, "paw")


#: 形态名。2026-10-15 起球是唯一形态（桌宠与整套宠物模型资源已移除）——
#: 保留这个名字是为了让 `build_form()` 的入参和配置里的写法仍有意义，
#: 也让「再加一种形态」不必改调用方。
DEFAULT_FORM = "orb"

#: 形态名 → 构造函数。
FORM_BUILDERS = {
    "orb": OrbForm,
}


def build_form(name: str, **kwargs) -> Form:
    """按名字建形态。未知名字回退到球（永不返回 None）。"""
    builder = FORM_BUILDERS.get((name or "").strip().lower(), OrbForm)
    return builder(**kwargs)
