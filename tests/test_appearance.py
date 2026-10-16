# -*- coding: utf-8 -*-
"""外观形态（`Form`）与外壳（`ShellWindow`）的回归测试。

这份测试守的是 2026-10-14 那次「外壳 / 外观分层」重构的结构性属性：

    · **分层**：换形态不动窗口行为，也不动插件契约（`ui_manager.window`）
    · **协议**：注册进来的每个形态都满足 `Form` 协议（含缺省值 ——
      基类本身就是一个「什么都用默认」的合法形态）
    · **位置**：位置按**中心点**持久化 —— 形态尺寸随配置变化时不漂
    · **气泡**：独立顶层窗口（球窗 64px 放不下窗口内气泡）
    · **贴边**：按**窗口所在那块屏**算，不是主屏
    · **输入**：单击仍是「戳一下」（发 PET_CLICKED），双击才开控制中心

2026-10-15 起球是唯一在册形态（桌宠与整套宠物模型资源已移除），
但 `Form` 协议与 `FORM_BUILDERS` 的注册机制保留 —— 这份测试对
「再加一种形态」仍然成立。

运行:
    python dev_bootstrap.py -m pytest tests/test_appearance.py -q
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QMouseEvent, QPainter, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QWidget

app = QApplication.instance() or QApplication([])

from presentation.anim_controller import AnimController
from presentation.bubble import Bubble
from presentation.forms import (
    DEFAULT_FORM,
    FORM_BUILDERS,
    Form,
    OrbForm,
    build_form,
)
from presentation.ui_renderer import ShellWindow, UIManager, _build_initial_form

#: 球的进度弧色 #4CC2FF —— 只用来在像素里认出「这一段填过了」。
_PROGRESS_RGB = (76, 194, 255)


# ---------------------------------------------------------------- 辅助

def _render(form: Form) -> QImage:
    """把形态画到透明画布上。

    刻意排除 `DrawWindowBackground` —— 默认的 `grab()` 会把未绘制区域
    填成不透明，于是「球外面应该是透明的」这条根本量不出来。
    """
    img = QImage(form.size(), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    form.render(p, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
    p.end()
    return img


def _count_progress_pixels(img: QImage) -> int:
    """数进度弧上的像素（用颜色认，不靠几何 —— 免得跟实现耦合）。"""
    r0, g0, b0 = _PROGRESS_RGB
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if (c.alpha() > 200 and abs(c.red() - r0) < 40
                    and abs(c.green() - g0) < 40 and abs(c.blue() - b0) < 40):
                n += 1
    return n


def _count_ring_pixels(img: QImage, low: int, high: int) -> int:
    """数环带上「中性灰、亮度落在 [low, high)」的像素。

    底槽与关闭环都是中性灰，区别只在亮度 —— 所以用亮度分档来认。
    """
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() < 150:
                continue
            if abs(c.red() - c.green()) > 14 or abs(c.green() - c.blue()) > 14:
                continue
            if low <= c.red() < high:
                n += 1
    return n


def _max_alpha(img: QImage, x0: int, y0: int, x1: int, y1: int) -> int:
    """矩形区域内的最大 alpha。"""
    best = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            a = img.pixelColor(x, y).alpha()
            if a > best:
                best = a
    return best


def _mouse(event_type, button=Qt.MouseButton.LeftButton):
    return QMouseEvent(
        event_type, QPointF(5.0, 5.0), QPointF(5.0, 5.0),
        button, button, Qt.KeyboardModifier.NoModifier,
    )


def _avail():
    """当前屏的可用区。测试里一律以它为期望基准，不写死坐标。"""
    return QGuiApplication.primaryScreen().availableGeometry()


def _fake_ui_manager(shell: ShellWindow, controller) -> UIManager:
    """只装 `_sync_anim_target` / `_stop_animations` 需要的那两个属性的 UIManager。

    用 `__new__` 跳过 `__init__`（它会建 QApplication、读配置、挂插件），
    但调的仍是**真方法** —— 不然测的是替身，不是产品代码。
    """
    mgr = UIManager.__new__(UIManager)
    mgr.window = shell
    mgr.anim_controller = controller
    return mgr


# ================================================================
# 1. 协议一致性
# ================================================================

def test_default_form_is_registered():
    """默认形态必须是注册过的 —— 否则启动就回退，配置形同虚设。"""
    assert DEFAULT_FORM in FORM_BUILDERS


def test_default_appearance_is_the_orb():
    """常态外观默认是悬浮球。

    这条守的是「换默认」这件事本身：只把 `DEFAULT_FORM` 改掉的话，
    注册断言照样通过；而 `_build_initial_form()` 对空名与未知名一律
    回退到球，配置接不上时会静默变成一个别的尺寸的球。
    """
    from data.config_manager import config_manager

    assert DEFAULT_FORM == "orb"
    assert config_manager.get("appearance.orb_size") == 52, (
        "配置默认值没跟着改 —— DEFAULT_CONFIG 与 config.default.json 要同时改"
    )
    assert isinstance(_build_initial_form(), OrbForm), (
        "不带参数构造出来的不是球 —— 说明配置或 _build_initial_form 没接上"
    )


def test_ui_manager_window_is_still_a_usable_dialog_parent():
    """`ui_manager.window` 是既有契约：插件拿它当对话框的父窗口。

    换形态只换内胆，**契约面不动** —— 所以这里不测「窗口长什么样」，
    而是照插件的真实用法走一遍（`extensions/system/timer/plugin.py`
    的 `self.app.ui_manager.window`）。
    """
    from presentation.ui_renderer import UIManager

    mgr = UIManager()
    # 插件都先判空再用（UI 就绪前 window 是 None）
    assert mgr.window is None

    mgr.window = ShellWindow(OrbForm())
    assert isinstance(mgr.window, QWidget)

    dialog = QDialog(mgr.window)          # 插件就是这么用的
    try:
        assert dialog.parent() is mgr.window
    finally:
        dialog.deleteLater()


def test_registered_forms_satisfy_the_protocol():
    """注册进来的每个形态都要能回答协议里的每一个问题。

    缺一个方法的话，外壳调过去就是 AttributeError —— 而且只在切到
    那个形态时才炸，属于「上线才发现」的类型。
    """
    for name in FORM_BUILDERS:
        form = build_form(name)
        assert isinstance(form, Form), name
        assert isinstance(form.form_size().width(), int), name
        assert form.form_size().width() > 0, name
        assert isinstance(form.wants_edge_snap(), bool), name
        assert isinstance(form.edge_snap_inset(), int), name
        assert isinstance(form.edge_snap_trigger(), int), name
        # animation_target 允许是 None（球没有精灵图），但方法必须在
        target = form.animation_target()
        assert target is None or isinstance(target, QLabel), name


class _BareForm(Form):
    """只实现 `form_size()` 的最小形态 —— 用来钉住基类的缺省值。

    基类的缺省值本身就是协议的一部分：一个「静态显示、不参与动画与
    状态」的外观不该被逼着实现六个钩子。
    """

    def form_size(self):
        return QSize(80, 80)


def test_bare_form_uses_the_protocol_defaults():
    """基类缺省值：不换图、允许位移动画、用配置透明度、不贴边。"""
    form = _BareForm()
    assert form.animation_target() is None
    assert form.wants_shell_motion() is True
    assert form.preferred_opacity() is None
    assert form.wants_edge_snap() is False
    assert form.edge_snap_inset() == 0
    assert form.edge_snap_trigger() == 0


def test_unknown_form_name_falls_back_to_a_real_form():
    """配置写错不该让窗口变成 0×0 直接消失。"""
    form = _build_initial_form("no-such-form")
    assert isinstance(form, OrbForm)
    assert form.form_size().width() >= 60


def test_form_size_follows_the_configured_diameter():
    """形态自己决定窗口尺寸，且尊重配置给的直径 —— 这是 `form_size()` 存在的理由。"""
    default = OrbForm().form_size()
    bigger = OrbForm(90).form_size()
    assert default != bigger
    assert bigger.width() > default.width()


# ================================================================
# 2. 悬浮球的外观
# ================================================================

def test_orb_is_square_with_a_round_body():
    """球体是圆的，而且**球外面是透明的**（不然会挡到桌面的点击）。"""
    form = OrbForm()
    size = form.form_size()
    assert size.width() == size.height()

    img = _render(form)
    mid = size.width() // 2
    assert img.pixelColor(mid, mid).alpha() > 200, "球心应该是实的"
    assert img.pixelColor(1, 1).alpha() == 0, "左上角应该在球外、全透明"
    assert img.pixelColor(size.width() - 2, size.height() - 2).alpha() == 0


def test_orb_ring_grows_with_the_ratio():
    """进度弧要**真的**按比例画。

    用非等距的两个比例（0.1 / 0.9）—— 等距输入会让「按比例」与
    「画固定几段」结果相同，断言会退化成永真（P2.14 踩过）。
    """
    form = OrbForm()
    form.set_progress(0.1, True)
    low = _count_progress_pixels(_render(form))
    form.set_progress(0.9, True)
    high = _count_progress_pixels(_render(form))

    assert low > 0, "0.1 的进度弧一个像素都没画出来"
    assert high > low * 2, f"0.9 的弧没比 0.1 明显长（{low} -> {high}）"


def test_orb_off_state_draws_a_dim_full_ring_not_an_empty_one():
    """「没在记录」要画成**灰色整环**，不是空环。

    空环会被读成「今天一点没干」，而真相是「根本没在采集」——
    这两件事对用户的含义完全不同（与托盘图标同一个约定）。

    判据用「环带上中性灰、亮度落在 [100,180) 的像素数」：
    底槽叠在球体上约 76（不在带内），关闭环约 128（在带内），
    白描边与图标是 255（不在带内）。
    """
    form = OrbForm()
    form.set_progress(0.0, False)
    off = _render(form)
    # 关闭态的环是「中性灰、偏亮」的那一档
    off_ring = _count_ring_pixels(off, 100, 180)

    form.set_progress(0.0, True)
    active = _render(form)
    active_ring = _count_ring_pixels(active, 100, 180)

    assert off_ring > active_ring * 2, (
        f"关闭态与常态的环看不出差别（{off_ring} vs {active_ring}）"
    )


def test_orb_sleep_is_dimmer_than_idle():
    """休眠态整体压暗 —— 这是球表达「sleep」的唯一介质（没有精灵图）。

    压暗由**两处**共同完成，两条都要钉住：
      · 球体填充更透明（`_ORB_FILL_DIM`：205 → 135）
      · 中心图标半透明（`p.setOpacity(0.55)`）

    只测球心是抓不全的 —— 反向验证当场发现：球心恰好落在**月牙的空心处**，
    量到的是填充，于是「图标不压暗」照样通过。
    """
    form = OrbForm()
    mid = form.width() // 2
    fill_y = mid + 14                              # 球内、图标外、环内侧
    # 21px 的图标框内缩一点。它在球体（r=26）内、进度环（r 18~23）内侧，
    # 所以框里只可能有**填充**与**图标**两样东西 —— 不会被环或白描边干扰。
    icon_box = (mid - 9, mid - 9, mid + 9, mid + 9)

    form.set_state("idle")
    idle = _render(form)
    form.set_state("sleep")
    sleep = _render(form)

    # ① 球体填充本身
    idle_fill = idle.pixelColor(mid, fill_y).alpha()
    sleep_fill = sleep.pixelColor(mid, fill_y).alpha()
    assert idle_fill > 200, f"取样点没落在球体填充上（alpha={idle_fill}）"
    assert sleep_fill < idle_fill - 40, (
        f"球体填充没跟着压暗（{sleep_fill} vs {idle_fill}）"
    )

    # ② 中心图标本身（取框内最亮像素）
    idle_icon = _max_alpha(idle, *icon_box)
    sleep_icon = _max_alpha(sleep, *icon_box)
    assert idle_icon >= 250, f"图标框里没取到图标（alpha={idle_icon}）"
    assert sleep_icon < idle_icon - 40, (
        f"图标没跟着压暗（{sleep_icon} vs {idle_icon}）"
    )


def test_orb_hover_enlarges_the_ball():
    """悬停要**看得出**放大：在球体外沿附近取一点，常态透明、悬停不透明。"""
    form = OrbForm()
    probe_x = form.width() // 2 + 27      # 常态半径 26 → 球外；悬停 28.1 → 球内
    probe_y = form.height() // 2

    form._hover = False
    assert _render(form).pixelColor(probe_x, probe_y).alpha() == 0, "取样点本来就在球内"
    form._hover = True
    assert _render(form).pixelColor(probe_x, probe_y).alpha() > 0, "悬停没有放大球体"


def test_orb_bounce_actually_changes_the_scale():
    """被戳要弹一下 —— 不是「调了动画对象但没接到绘制上」。"""
    form = OrbForm()
    assert form.pulse() == 1.0
    form.set_state("interact")
    # 动画是异步的：手动驱动一次中间值，确认它真的接到了绘制用的系数上
    form._on_pulse(1.15)
    assert form.pulse() == 1.15
    before = _render(form)
    form._on_pulse(1.0)
    after = _render(form)
    assert before != after, "脉冲值变了但画面没变 —— 系数没接进 paintEvent"


def test_orb_forces_an_opaque_window():
    """球体自带半透明，窗口级再叠一层透明度会糊 —— 球要否决配置值。"""
    assert OrbForm().preferred_opacity() == 1.0


# ================================================================
# 3. 外壳与形态的协作
# ================================================================

def test_animation_target_follows_the_form():
    """动画落点由形态决定：球没有精灵图，返回 None。

    外壳只是转发 ——  `ShellWindow.animation_target()` 在形态缺失时
    同样返回 None，两种「没有落点」都不能变成 QLabel。
    """
    shell = ShellWindow(OrbForm())
    assert shell.animation_target() is None
    assert OrbForm().animation_target() is None


def test_shell_motion_is_a_form_decision():
    """窗口能不能被动画 `move()` 走，由**形态**决定。

    球是用户摆好的常驻指示，还要贴边 —— 被动画挪走就散了
    （实测：拖到 (900,500)，动画结束停在 (470,300)，偏 430px）。
    外壳只负责转发，不自己下结论。
    """
    assert OrbForm().wants_shell_motion() is False
    shell = ShellWindow(OrbForm())
    assert shell.wants_shell_motion() is False


def test_the_orb_shell_is_not_handed_to_the_animation_controller():
    """球的外壳不能进数值动画的位移目标。

    数值动画是按**动画开始时的坐标**去 `move()` 的。把球交给它，
    用户拖动后下一 tick 就把球拽回原处（实测偏 430px）。
    """
    shell = ShellWindow(OrbForm())
    ctrl = AnimController()
    mgr = _fake_ui_manager(shell, ctrl)

    mgr._sync_anim_target()
    assert ctrl._target_widget is None, "球被交给了位移动画"

    # 换成「想要位移」的形态时必须装回去 —— 否则那种形态的弹跳 / 摇一摇全没了
    shell.set_form(_BareForm())
    mgr._sync_anim_target()
    assert ctrl._target_widget is shell, "想要位移动画的外壳没被装回去"


def test_orb_stays_put_while_an_animation_plays():
    """动画播到一半把球拖走 → 球停在用户落点。"""
    shell = ShellWindow(OrbForm())
    ctrl = AnimController()
    ctrl.set_target_widget(None)          # 球：`_sync_anim_target` 给的就是 None
    shell.move(QPoint(500, 300))
    shell.show()
    try:
        ctrl.play("wave")                 # rotation (-15,15) → ±30px，1200ms
        QTest.qWait(300)                  # 动画中途
        shell.move(QPoint(900, 500))
        QTest.qWait(1200)                 # 等动画跑完
        assert shell.pos() == QPoint(900, 500), (
            f"球被动画挪走了：{shell.pos().toTuple()}"
        )
    finally:
        ctrl.stop()
        shell.hide()


def test_grabbing_the_window_stops_the_animation():
    """用户按住窗口 → 位移动画立刻停，并把窗口放回它自己的起点。

    不这么做的话，位移动画会把用户拖动后的位置拽回去
    （实测：拖到 (900,500)，动画结束后停在 (470,300)）。
    这里手工把外壳设成动画目标，与形态无关地验这条门控。
    """
    shell = ShellWindow(OrbForm())
    ctrl = AnimController()
    ctrl.set_target_widget(shell)
    shell._ui_manager = _fake_ui_manager(shell, ctrl)
    shell.move(QPoint(500, 300))
    shell.show()
    try:
        ctrl.play("wave")
        QTest.qWait(300)
        assert ctrl._numeric_origin is not None, "动画没在跑，测不到「按住即停」"

        shell.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress))
        assert ctrl._numeric_origin is None, "按住之后动画还在跑"
        assert shell.pos() == QPoint(500, 300), "动画被打断后没把窗口放回起点"

        # 松手后拖走 → 不该再被拽回
        shell.move(QPoint(900, 500))
        QTest.qWait(1200)
        assert shell.pos() == QPoint(900, 500), (
            f"拖动后被动画拽回：{shell.pos().toTuple()}"
        )
    finally:
        ctrl.stop()
        shell.hide()


def test_switching_form_resizes_the_window():
    shell = ShellWindow(OrbForm())
    orb_w = shell.width()
    shell.set_form(OrbForm(90))
    assert shell.width() > orb_w
    assert shell.width() == shell.form().form_size().width()


def test_switching_form_keeps_the_centre():
    """换形态**中心点不动**。

    按左上角对齐的话，小尺寸形态换大尺寸形态会往右下飘 ——
    用户会以为窗口「自己跑了」。
    """
    shell = ShellWindow(OrbForm())
    shell.move(_avail().center() - QPoint(50, 50))
    before = shell.geometry().center()
    shell.set_form(OrbForm(90))
    after = shell.geometry().center()
    assert abs(before.x() - after.x()) <= 1 and abs(before.y() - after.y()) <= 1, (
        f"换形态后中心漂了：{before} -> {after}"
    )


def test_switching_form_replaces_the_old_one():
    """旧形态必须被摘掉 —— 否则它会继续挂在窗口上参与绘制。"""
    shell = ShellWindow(OrbForm())
    old = shell.form()
    shell.set_form(OrbForm(90))
    assert shell.form() is not old
    assert old.parent() is None


def test_position_is_remembered_as_a_centre():
    """持久化的是中心点，不是左上角。"""
    from data.config_manager import config_manager

    shell = ShellWindow(OrbForm())
    shell.move(_avail().center() - QPoint(30, 30))
    expected = shell.geometry().center()
    shell._remember_center()

    saved = config_manager.get("window.center")
    assert isinstance(saved, (list, tuple)) and len(saved) == 2
    assert abs(int(saved[0]) - expected.x()) <= 1
    assert abs(int(saved[1]) - expected.y()) <= 1


# ================================================================
# 4. 贴边吸附
# ================================================================

def test_snap_puts_the_orb_against_the_screen_edge():
    """球要吸附到最近的屏幕边缘，并藏起一截。"""
    shell = ShellWindow(OrbForm())
    avail = _avail()
    inset = shell.form().edge_snap_inset()
    assert inset > 0, "球应该藏一截，否则贴边没意义"

    shell.move(avail.left() + 20, avail.center().y() - shell.height() // 2)
    shell._snap_to_edge()
    assert shell.is_snapped() is True
    assert shell.edge_side() == "left"
    assert shell.x() == avail.left() - inset

    shell.move(avail.right() - 60, avail.center().y() - shell.height() // 2)
    shell._snap_to_edge()
    assert shell.edge_side() == "right"
    assert shell.x() == avail.right() + 1 - shell.width() + inset


def test_snap_only_triggers_near_the_screen_sides():
    """**只有靠近两侧才吸** —— 屏幕中间松手要就地停住。

    原来是无条件按「中心点在哪半屏」吸：球在正中也会被拽到边上。
    用户亲手摆的位置被系统推翻，比不吸附更烦人。

    边界用 `trigger` 与 `trigger + 1` 两侧取样 —— 只测「中间不吸 / 边上吸」
    的话，把 trigger 写死成任意值都照样过。
    """
    shell = ShellWindow(OrbForm())
    avail = _avail()
    trigger = shell.form().edge_snap_trigger()
    assert trigger > 0, "球必须给出触发距离，否则这个门控形同虚设"
    y = avail.center().y() - shell.height() // 2

    # 屏幕正中 → 离两边都远，不该动
    shell.move(avail.center().x() - shell.width() // 2, y)
    before = shell.pos()
    shell._snap_to_edge()
    assert shell.pos() == before, "在屏幕中间松手也被吸到边上了"
    assert shell.is_snapped() is False
    assert shell.edge_side() is None

    # 刚好在触发距离内 → 吸
    shell.move(avail.left() + trigger, y)
    shell._snap_to_edge()
    assert shell.edge_side() == "left"

    # 刚刚超出触发距离 → 不吸
    shell.move(avail.left() + trigger + 1, y)
    shell._snap_to_edge()
    assert shell.edge_side() is None, "触发距离没被真的读，多出 1px 也吸了"


def test_dragging_away_from_the_edge_clears_the_snap():
    """从贴边拖到中间 → 必须解除吸附态。

    否则 `leaveEvent`（鼠标一移开）会照着 `_edge_side` 把窗口拽回边缘 ——
    用户刚摆好的位置又没了。
    """
    shell = ShellWindow(OrbForm())
    avail = _avail()
    y = avail.center().y() - shell.height() // 2

    shell.move(avail.left() + 10, y)
    shell._snap_to_edge()
    assert shell.is_snapped() is True

    shell.move(avail.center().x() - shell.width() // 2, y)
    shell._snap_to_edge()
    assert shell.is_snapped() is False
    assert shell.edge_side() is None

    # 鼠标移开时不该再吸回去
    shell.leaveEvent(QEvent(QEvent.Type.Leave))
    assert shell.is_snapped() is False


def test_snap_is_skipped_for_forms_that_do_not_want_it():
    """不想贴边的形态换进来后，外壳不许替你吸。

    门控读的是形态自己的回答（`wants_edge_snap()`），不是外壳硬编码 ——
    不然「加一种不该贴边的形态」这件事根本切不进来。
    """
    shell = ShellWindow(_BareForm())
    avail = _avail()
    shell.move(avail.left() + 20, avail.center().y() - shell.height() // 2)
    before = shell.pos()
    shell._snap_to_edge()
    assert shell.pos() == before
    assert shell.is_snapped() is False


def test_expanding_from_the_edge_brings_the_whole_ball_back():
    """鼠标移入时要完全露出（否则用户点不到藏在屏幕外的那半）。"""
    shell = ShellWindow(OrbForm())
    avail = _avail()
    shell.move(avail.left() + 20, avail.center().y() - shell.height() // 2)
    shell._snap_to_edge()
    assert shell.x() < avail.left()          # 确实藏了一截

    shell._expand_from_edge()
    assert shell.x() == avail.left()
    assert shell.is_snapped() is False


def test_off_screen_position_is_recovered():
    """分辨率变了 / 显示器拔了之后，窗口不能整个落在屏幕外。"""
    shell = ShellWindow(OrbForm())
    shell.move(99999, 99999)
    shell._ensure_on_screen()
    assert QGuiApplication.screenAt(shell.geometry().center()) is not None


def test_snap_does_not_move_vertically_out_of_the_work_area():
    """吸附只动水平方向，垂直方向要夹在工作区内（不能钻到任务栏底下）。"""
    shell = ShellWindow(OrbForm())
    avail = _avail()
    shell.move(avail.left() + 20, avail.bottom() + 500)
    shell._snap_to_edge()
    assert avail.top() <= shell.y() <= avail.bottom() - shell.height() + 1


# ================================================================
# 5. 气泡
# ================================================================

def test_bubble_is_a_separate_top_level_window():
    """气泡必须是独立顶层窗口 —— 球窗只有 64px，放窗口里会被裁掉。"""
    bubble = Bubble()
    assert bubble.parent() is None
    assert bubble.isWindow()
    flags = bubble.windowFlags()
    assert flags & Qt.WindowType.Tool
    assert flags & Qt.WindowType.FramelessWindowHint
    # 纯展示：不能吃鼠标，否则浮在球上方会挡住点球
    assert bubble.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_bubble_places_itself_above_the_anchor():
    anchor = ShellWindow(OrbForm())
    avail = _avail()
    anchor.move(avail.center() - QPoint(anchor.width() // 2, 0))
    bubble = Bubble()
    bubble.show_text("测试", anchor, 1000)
    try:
        assert bubble.isVisible()
        assert bubble.y() + bubble.height() <= anchor.y(), "气泡没有落在锚点上方"
        assert abs(bubble.geometry().center().x() - anchor.geometry().center().x()) <= 2
    finally:
        bubble.hide()


def test_bubble_falls_below_when_there_is_no_room_above():
    """锚点贴着屏幕顶端时，气泡要翻到下方，而不是跑到屏幕外。"""
    anchor = ShellWindow(OrbForm())
    avail = _avail()
    anchor.move(avail.left() + 100, avail.top())
    bubble = Bubble()
    bubble.show_text("贴顶", anchor, 1000)
    try:
        assert bubble.y() >= anchor.geometry().bottom(), "上方放不下时没有翻到下方"
        assert bubble.y() >= avail.top(), "气泡跑到屏幕外了"
    finally:
        bubble.hide()


def test_shell_shows_text_through_the_bubble():
    shell = ShellWindow(OrbForm())
    shell.show_text("嗨", 500)
    try:
        assert shell._bubble.isVisible()
        assert shell._bubble.text() == "嗨"
    finally:
        shell._bubble.hide()


# ================================================================
# 6. 页面文案
# ================================================================

class _FakeCenter:
    """够 `Page` 构造与动作回调用的最小替身。"""

    app = None

    def confirm(self, *args, **kwargs) -> bool:
        return False

    def info(self, *args, **kwargs) -> None:
        pass

    def warn(self, *args, **kwargs) -> None:
        pass

    def refresh_status(self) -> None:
        pass


def _label_texts(widget) -> str:
    """控件树里所有 QLabel 的文字，拼成一坨便于 `in` 判断。"""
    return "\n".join(lbl.text() for lbl in widget.findChildren(QLabel))


def test_appearance_page_drops_the_redundant_hints():
    """外观页的两句说明是废话 —— 页面名和卡片标题已经说清了同一件事。

    （用户 2026-10-14 明确要求去掉：副标题「主题、形象与窗口行为。
    主题切换会立即生效并保存。」与配色说明「深色参考 VS Code Dark+…」。）
    """
    from presentation.control_center import AppearancePage

    page = AppearancePage(_FakeCenter(), None)
    texts = _label_texts(page)
    assert "主题、形象与窗口行为" not in texts
    assert "深色参考" not in texts
    assert "浅色参考" not in texts


# ================================================================
# 6. 输入：单击戳一下，双击开窗口
# ================================================================

def test_single_click_still_publishes_pet_clicked():
    """单击保持桌宠时代的行为：发 PET_CLICKED（状态机进 interact 5 秒）。

    球没有精灵图，但这条**事件**是形态无关的契约 —— 换了形态也得发。
    """
    from event_bus import event_bus

    got = []
    event_bus.subscribe("PET_CLICKED", lambda e: got.append(e))

    shell = ShellWindow(OrbForm())
    shell.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress))
    assert len(got) == 1, "单击没有发 PET_CLICKED"


def test_double_click_opens_the_control_center(monkeypatch):
    """双击才开主窗口 —— 这样单击不必延迟 250ms 等双击判定。"""
    shell = ShellWindow(OrbForm())
    opened = []
    monkeypatch.setattr(shell, "_open_control_center", lambda: opened.append(1))

    shell.mouseDoubleClickEvent(_mouse(QEvent.Type.MouseButtonDblClick))
    assert opened == [1]


def test_right_click_opens_the_plugin_menu(monkeypatch):
    """右键菜单是插件契约的一部分，换了形态不能丢。"""
    shell = ShellWindow(OrbForm())
    shown = []
    monkeypatch.setattr(shell, "_show_context_menu", lambda pos: shown.append(pos))
    shell.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, Qt.MouseButton.RightButton))
    assert len(shown) == 1


if __name__ == "__main__":
    raise SystemExit("请用 pytest 运行：python dev_bootstrap.py -m pytest tests/test_appearance.py -q")
