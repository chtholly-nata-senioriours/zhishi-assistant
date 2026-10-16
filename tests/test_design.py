# -*- coding: utf-8 -*-
"""设计系统（presentation/design/）的回归测试。

这份测试守的是**规格**，不是实现细节。用户给的硬性要求：
    · 所有颜色收敛到一个 Theme 类里，**QSS 中禁止写死 hex**
    · 字体一律 pt（DPI 自适应），禁止写死 px 字号
    · 间距 4px 基准栅格；圆角 2px、按钮 3px（不追求大圆角）
    · 数据密集区行高 28px；滚动条 8px、hover 变宽
    · 日志只有级别标签着色，正文不上色
    · 空状态要有引导文案
    · QSS 选择器精确到控件类，不用全局 `QWidget`（窗口级用 `.QWidget`）

运行:
    python tests/test_design.py
    pytest tests/test_design.py -v
"""
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from presentation.design import icons, install, qss, reset_for_tests, set_theme, theme, tokens

app = QApplication.instance() or QApplication([])

REPO = Path(__file__).resolve().parent.parent


def _theme(dark: bool):
    reset_for_tests()
    set_theme("dark" if dark else "light", persist=False)
    return theme()


# ============================================================
# 1. 颜色收敛：QSS 源码里不允许出现 hex 字面量
# ============================================================

def test_qss_source_has_no_hex_literals():
    """规格硬要求：「禁止在 QSS 中写死颜色 hex 值」。

    颜色只能来自 tokens.py 的 PALETTES —— 否则换主题时这一处不会变。
    """
    src = (REPO / "presentation" / "design" / "qss.py").read_text(encoding="utf-8")
    hits = [ln.strip() for ln in src.splitlines()
            if re.search(r"#[0-9a-fA-F]{3,8}\b", ln) and not ln.strip().startswith("#")]
    assert hits == [], f"qss.py 里出现了 hex 字面量: {hits[:5]}"


def test_no_inline_stylesheet_with_hex_in_ui_code():
    """UI 代码里也不许用内联样式表写死颜色（颜色必须来自 token）。"""
    bad = []
    for path in list((REPO / "presentation").rglob("*.py")) + \
            list((REPO / "extensions").rglob("*.py")):
        if "design" in path.parts:
            continue
        for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "setStyleSheet" in ln and re.search(r"#[0-9a-fA-F]{3,8}\b", ln):
                bad.append(f"{path.relative_to(REPO)}:{i}")
    assert bad == [], f"内联样式表写死了颜色: {bad}"


def test_generated_qss_has_no_unresolved_placeholders():
    for dark in (False, True):
        s = qss.build_qss(_theme(dark))
        left = re.findall(r"\{[A-Za-z_]+\}", s)
        assert left == [], f"QSS 里有未替换的占位符: {set(left)}"


def test_light_and_dark_qss_differ():
    light = qss.build_qss(_theme(False))
    dark = qss.build_qss(_theme(True))
    assert light != dark
    assert "#F3F3F3" in light.upper()      # 浅色窗口底
    assert "#252526" in dark.upper()        # 深色窗口底


# ============================================================
# 2. 尺寸 / 圆角 / 字体 规格
# ============================================================

def test_radius_spec():
    """规格：圆角 2px，按钮 3px，不追求大圆角。"""
    assert tokens.RADIUS["window"] == 2
    assert tokens.RADIUS["control"] == 2
    assert tokens.RADIUS["button"] == 3


def test_spacing_is_4px_grid():
    for name, px in tokens.SPACING.items():
        assert px % 4 == 0, f"SPACING['{name}']={px} 不在 4px 栅格上"


def test_row_and_control_height():
    """规格：数据密集区行高紧凑（28px 左右）。"""
    assert tokens.ROW_HEIGHT == 28
    assert tokens.CONTROL_HEIGHT == 28


def test_scrollbar_is_narrow():
    """规格：8px 窄滚动条，hover 变宽。"""
    assert tokens.SCROLLBAR_WIDTH == 8
    assert tokens.SCROLLBAR_WIDTH_HOVER > tokens.SCROLLBAR_WIDTH


def test_font_size_is_pt_not_px():
    """规格：9pt，禁止写死像素字号。"""
    assert tokens.FONT_SIZE == 9
    s = qss.build_qss(_theme(True))
    # 字号一律带 pt；font-size 后面不该出现 px
    for m in re.finditer(r"font-size:\s*([\d.]+)(pt|px)", s):
        assert m.group(2) == "pt", f"QSS 里出现 px 字号: {m.group(0)}"


def test_mono_font_used_for_log_view():
    s = qss.build_qss(_theme(True))
    m = re.search(r"QPlainTextEdit#logView[^{]*\{(.*?)\}", s, re.S)
    assert m, "找不到 #logView 规则"
    assert "font-family" in m.group(1)


# ============================================================
# 3. QSS 选择器纪律
# ============================================================

def test_no_bare_qwidget_type_selector():
    """规格：禁止全局 QWidget 选择器，窗口级用 `.QWidget`。

    裸 `QWidget` 会波及所有子类，把按钮/输入框自己的背景一起覆盖掉。
    """
    s = qss.build_qss(_theme(True))
    # 去掉 .QWidget（合法的窗口级写法）后，不该再有裸 QWidget 选择器
    stripped = s.replace(".QWidget", "")
    for m in re.finditer(r"(^|\n)\s*QWidget\s*(,|\{)", stripped):
        raise AssertionError(f"出现裸 QWidget 选择器: {m.group(0)!r}")


def test_toolbar_button_has_four_states():
    """规格：工具栏按钮必须有 hover / pressed / checked / disabled 四态。"""
    s = qss.build_qss(_theme(True))
    for state in (":hover", ":pressed", ":checked", ":disabled"):
        assert f"QToolButton{state}" in s, f"QToolButton 缺少 {state} 态"


def test_pushbutton_has_four_states():
    s = qss.build_qss(_theme(True))
    for state in (":hover", ":pressed", ":disabled"):
        assert f"QPushButton{state}" in s, f"QPushButton 缺少 {state} 态"


def test_scrollbar_has_hover_widening():
    """规格：8px 窄滚动条，hover 变宽。

    实现是「轨道固定 + handle 内缩」：常态 margin 让 handle 收成 8px，
    hover 时 margin 归零撑满 12px 轨道。
    这里断言的是**行为**（hover 的 margin 必须更小），而不是某个具体选择器 ——
    否则换个等价写法（比如改 border 宽度）测试就会误报失败。
    """
    s = qss.build_qss(_theme(True))
    normal = re.search(r"QScrollBar::handle:vertical\s*\{(.*?)\}", s, re.S)
    hover = re.search(r"QScrollBar::handle:vertical:hover\s*\{(.*?)\}", s, re.S)
    assert normal and hover, "缺少滚动条 handle 的常态 / hover 规则"

    def margin_px(block: str) -> int:
        m = re.search(r"margin:\s*(\d+)px", block)
        return int(m.group(1)) if m else 0

    assert margin_px(hover.group(1)) < margin_px(normal.group(1)), \
        "hover 时 handle 没有变宽（margin 应减小到 0）"
    assert tokens.SCROLLBAR_WIDTH_HOVER == tokens.SCROLLBAR_WIDTH + 2 * margin_px(normal.group(1)), \
        "轨道宽度应当等于「常态 handle 宽 + 两侧内缩」"


# ============================================================
# 4. QPalette 兜底（Fusion 基样式）
# ============================================================

def test_qt_palette_matches_theme():
    """QSS 覆盖不到的地方（原生菜单、禁用态）靠 QPalette 上色。"""
    from PySide6.QtGui import QPalette

    t = _theme(True)
    p = qss.build_qt_palette(t)
    assert p.color(QPalette.ColorRole.Window).name().upper() == \
        t.color("window").name().upper()
    assert p.color(QPalette.ColorRole.Highlight).name().upper() == \
        t.color("accent").name().upper()


# ============================================================
# 5. 图标：内联 SVG，按主题着色
# ============================================================

def test_all_icons_render():
    assert len(icons.ICONS) > 20
    for name in icons.ICONS:
        markup = icons.svg_markup(name, "#FFFFFF")
        assert markup.startswith("<svg") and markup.rstrip().endswith("</svg>"), name


def test_icon_color_is_injected():
    """深浅色各一套 —— 同一图标传不同颜色必须产出不同 SVG。"""
    a = icons.svg_markup("gear", "#FFFFFF")
    b = icons.svg_markup("gear", "#000000")
    assert a != b
    assert "#FFFFFF" in a and "#000000" in b


def test_themed_icon_follows_current_theme():
    _theme(False)
    light = icons.themed("gear", "text").cacheKey()
    _theme(True)
    dark = icons.themed("gear", "text").cacheKey()
    assert light != dark, "图标没有跟随主题换色"


def test_unknown_icon_is_empty_not_crash():
    """图标名写错不该崩，只该是个空图标（便于在 UI 上发现）。"""
    assert icons.icon("no_such_icon_xyz").isNull()


# ============================================================
# 6. 控件
# ============================================================

def test_segmented_control_does_not_stretch():
    """分段选择器必须按内容收缩。

    第一版把 QToolButton 直接塞进 QHBoxLayout，而它的默认尺寸策略是
    Expanding —— 放进 QFormLayout 后被拉满宽，两个分段各占一半，
    看起来像一条空长条。
    """
    from PySide6.QtWidgets import QSizePolicy

    from presentation.design.widgets import SegmentedControl

    _theme(True)
    seg = SegmentedControl(["浅色", "深色"], 0)
    assert seg.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Preferred
    for btn in seg.findChildren(type(seg._group.button(0))):
        assert btn.sizePolicy().horizontalPolicy() != QSizePolicy.Policy.Expanding


def test_segmented_control_emits_on_change():
    from presentation.design.widgets import SegmentedControl

    _theme(True)
    seg = SegmentedControl(["A", "B"], 0)
    seen = []
    seg.changed.connect(seen.append)
    seg.set_index(1, emit=True)
    assert seen == [1]
    assert seg.index() == 1


def test_log_view_only_colors_level_tag():
    """规格：禁止整段彩色文字，只有级别标签着色。

    断言 HTML 里恰好只有一个着色 span 包住 `[LEVEL]`，正文不带颜色。
    """
    from presentation.design.widgets import LogView

    _theme(True)
    view = LogView()
    html = view._render("2026-10-10 18:00:00 [ERROR] pet_demo.x: 炸了")
    # 时间、级别、正文三段；只有「级别」这一段的颜色来自 log_* token
    assert "[ERROR]" in html
    assert html.count("<span") == 3
    t = theme()
    assert t.color("log_error").name() in html
    assert t.color("log_time").name() in html


def test_log_view_handles_unparsable_line():
    """非标准格式的行不该被丢掉，也不该抛异常。"""
    from presentation.design.widgets import LogView

    _theme(True)
    view = LogView()
    html = view._render("这是一行没有时间戳的文本")
    assert "这是一行没有时间戳的文本" in html


def test_empty_state_has_guidance_text():
    """规格：空状态要有引导文案，不是空白。"""
    from PySide6.QtWidgets import QLabel

    from presentation.design.widgets import EmptyState

    _theme(True)
    es = EmptyState("scroll", "还没有日志", "启动一段时间后回来看看")
    joined = " ".join(w.text() for w in es.findChildren(QLabel))
    assert "还没有日志" in joined
    assert "启动一段时间后回来看看" in joined


def test_nav_list_width_in_spec_range():
    """规格：左侧导航宽 200-240px。"""
    from presentation.design.widgets import NavList

    _theme(True)
    nav = NavList()
    lo, hi = tokens.NAV_WIDTH
    assert lo <= nav.minimumWidth() <= hi
    assert nav.maximumWidth() <= hi


def test_busy_cursor_context_manager():
    """规格：所有耗时操作给等待反馈，禁止界面卡死无提示。"""
    from presentation.design.widgets import busy_cursor

    _theme(True)
    with busy_cursor():
        assert QApplication.overrideCursor() is not None
    assert QApplication.overrideCursor() is None


# ============================================================
# 7. 控制中心（主窗口结构）
# ============================================================

def test_control_center_structure():
    """主窗口 = 工具栏 + 左导航 + QStackedWidget 工作区 + 状态栏。"""
    from PySide6.QtWidgets import QStackedWidget, QStatusBar, QToolBar

    from presentation.control_center import NAV_ITEMS, ControlCenter, reset_instance

    _theme(True)
    reset_instance()
    cc = ControlCenter(app=None)
    assert cc.findChild(QToolBar) is not None
    assert cc.findChild(QStackedWidget) is not None
    assert cc.findChild(QStatusBar) is not None
    assert len(cc._pages) == len(NAV_ITEMS)
    assert [p.title for p in cc._pages] == [label for _, label, _ in NAV_ITEMS]


def test_control_center_pages_all_switchable():
    """每一页都能通过 `goto(标题)` 切过去。

    注意**不能**再直接用 `setCurrentRow(i)` —— 导航插了分组标题行以后
    行号不再等于页序号（P2.14）。这里同时断言那张映射表是对的。
    """
    from presentation.control_center import ControlCenter, reset_instance

    _theme(True)
    reset_instance()
    cc = ControlCenter(app=None)
    assert len(cc._nav_rows) == len(cc._pages)
    for i, page in enumerate(cc._pages):
        cc.goto(page.title)
        app.processEvents()
        assert cc.current_page() is page, page.title


def test_nav_groups_cover_all_pages():
    """导航分组必须**一个不漏、一个不重**地覆盖全部页面。"""
    from presentation.control_center import NAV_GROUPS, NAV_ITEMS

    flat = [item for _group, items in NAV_GROUPS for item in items]
    assert flat == NAV_ITEMS
    titles = [label for _icon, label, _cls in flat]
    assert len(titles) == len(set(titles)), f"导航项重名: {titles}"
    for group, items in NAV_GROUPS:
        assert group.strip(), "分组名不能为空"
        assert items, f"分组「{group}」是空的"


def test_nav_group_headers_are_not_selectable():
    """分组标题行不能可选中 —— 否则用户点它会切到一个不存在的页面。"""
    from PySide6.QtCore import Qt

    from presentation.control_center import ControlCenter, reset_instance

    _theme(True)
    reset_instance()
    cc = ControlCenter(app=None)

    headers = [cc._nav.item(r) for r in range(cc._nav.count())
               if r not in cc._nav_rows]
    assert headers, "导航里没有分组标题行"
    for item in headers:
        assert not bool(item.flags() & Qt.ItemFlag.ItemIsSelectable), item.text()
        assert bool(item.flags() & Qt.ItemFlag.ItemIsEnabled), item.text()


def test_control_center_opens_today_page_by_default():
    """默认打开「今日」—— 主功能不能藏在设置后面（P2.14）。"""
    from presentation.control_center import ControlCenter, reset_instance

    _theme(True)
    reset_instance()
    cc = ControlCenter(app=None)
    assert cc._pages[0].title == "今日"
    assert cc.current_page().title == "今日"


def test_axis_labels_placed_at_exact_fractions():
    """刻度标签必须落在**精确比例位置**。

    为什么必须用**非等距**的刻度来测
        时间轴那 5 个刻度（0 / .25 / .5 / .75 / 1）**恰好是等距的** ——
        于是「按比例摆」和「均分成 n 份摆」结果一模一样，
        这条断言就分不出对错了（反向验证时真的没打红）。
        所以另加一组非等距的：只有它才能证明控件真的读了这个 fraction。
    """
    from presentation.design.charts import AxisLabels

    _theme(False)

    # ① 真实用法：时间轴的 5 个刻度
    axis = AxisLabels()
    axis.resize(400, 18)
    axis.set_labels(((0.0, "0:00"), (0.25, "6:00"), (0.5, "12:00"),
                     (0.75, "18:00"), (1.0, "24:00")))
    assert axis.count() == 5
    assert axis.text_at(1) == "6:00"
    center = axis.label_x(1) + axis._labels[1].width() / 2
    assert abs(center - 100) <= 3, center
    assert axis.label_x(0) == 0                                  # 第一个左对齐
    assert axis.label_x(4) + axis._labels[4].width() == 400       # 最后一个右对齐

    # ② 非等距：均分实现会把这些摆到 0 / 133 / 266 / 400 上，必然打红
    skewed = AxisLabels()
    skewed.resize(400, 18)
    skewed.set_labels(((0.0, "a"), (0.1, "b"), (0.5, "c"), (0.9, "d"), (1.0, "e")))
    for index, fraction in ((1, 0.1), (2, 0.5), (3, 0.9)):
        center = skewed.label_x(index) + skewed._labels[index].width() / 2
        assert abs(center - 400 * fraction) <= 3, (index, fraction, center)


def test_axis_labels_never_render_on_top_of_each_other():
    """可见的刻度标签**不许互相压住** —— 叠在一起就都读不出来了。

    密度是调用方按「应该标几个」定的，能不能放下得看实际字体宽度，
    只有控件自己知道。放不下时藏掉靠后的那一个，而不是叠着画。
    （P2.14 趋势页 30 天视图目检：首刻度糊成一团、末刻度也压住了。）
    """
    from PySide6.QtWidgets import QLabel

    from presentation.design.charts import AxisLabels

    _theme(False)

    axis = AxisLabels()
    axis.resize(120, 18)
    # 必须 show()：控件不可见时 Qt 会把 resizeEvent **延后**，
    # 下面那次「变宽」就触发不了重排，量到的是旧位置。
    axis.show()
    axis.set_labels([(f, f"刻度{i}") for i, f in
                     enumerate((0.0, 0.2, 0.4, 0.6, 0.8, 1.0))])
    assert axis.count() == 6, "藏起来的标签也要留在列表里（位置照算）"

    visible = [i for i in range(axis.count()) if not axis._labels[i].isHidden()]
    assert visible, "至少得留下一个刻度，否则这条轴等于没有"
    assert visible[0] == 0, "第一个必须留着（不然轴从哪儿开始都读不出）"

    last_right = None
    for i in visible:
        label = axis._labels[i]
        if last_right is not None:
            assert label.x() >= last_right, (
                f"第 {i} 个刻度压在别人身上：x={label.x()} < {last_right}"
            )
        last_right = label.x() + label.width()

    # 变宽以后要能重新显示出来 —— 藏起来不是永久拉黑
    axis.resize(1600, 18)
    assert all(not lab.isHidden() for lab in axis._labels), "变宽后应当全部显示"


def test_replacing_axis_labels_removes_the_old_ones_immediately():
    """换刻度必须**立刻**把旧的从界面上拿掉。

    `deleteLater()` 只是排队删除 —— 在真正销毁之前旧标签仍挂在父控件上、
    仍会被绘制。趋势页切「近 7 天 / 近 30 天」时目检到的重影就是这样来的：
    首刻度糊成一团、底部出现两个「0:00」。
    """
    from PySide6.QtWidgets import QLabel

    from presentation.design.charts import AxisLabels

    _theme(False)

    axis = AxisLabels()
    axis.resize(400, 18)
    axis.set_labels([(i / 4, f"旧{i}") for i in range(5)])
    assert len(axis.findChildren(QLabel)) == 5

    axis.set_labels([(i / 2, f"新{i}") for i in range(3)])
    assert axis.count() == 3
    assert len(axis.findChildren(QLabel)) == 3, "旧标签还挂在控件上，会被画出来"


def test_control_center_toolbar_buttons_are_icon_only():
    """规格：工具栏 iconOnly + tooltip。"""
    from PySide6.QtWidgets import QToolBar, QToolButton

    from presentation.control_center import ControlCenter, reset_instance

    _theme(True)
    reset_instance()
    cc = ControlCenter(app=None)
    toolbar = cc.findChild(QToolBar)
    # 排除 Qt 自己塞进来的溢出按钮（objectName 固定为 qt_toolbar_ext_button，
    # 既无文字也无 tooltip，不是我们的按钮）
    btns = [b for b in toolbar.findChildren(QToolButton)
            if b.objectName() != "qt_toolbar_ext_button"]
    assert btns, "工具栏里没有按钮"
    for b in btns:
        assert b.text() == "", f"工具栏按钮不该有文字: {b.text()!r}"
        assert b.toolTip(), "工具栏按钮必须有 tooltip"


def test_control_center_statusbar_shows_theme_and_model():
    from presentation.control_center import ControlCenter, reset_instance

    _theme(True)
    reset_instance()
    cc = ControlCenter(app=None)
    cc.refresh_status()
    assert "dark" in cc._lbl_theme.text()
    assert cc._lbl_model.text()


def _qss_rules(s: str) -> list[tuple[str, str]]:
    """把 QSS 粗解析成 (选择器, 规则体) 列表（够用即可，不追求完整解析）。

    先剥掉 `/* ... */` 注释 —— 否则注释会被当成选择器的一部分，
    断言失败时打印出来的「选择器」是一大段注释，看不出问题在哪。
    """
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", s)]


def test_no_qwidget_background_leak():
    """`.QWidget` **不能**带背景色。

    `.QWidget` 是 Qt 的精确类选择器，但它同样命中「卡片内部的普通
    QWidget 容器」—— 控制中心里每个表单行、分隔条、面板的动作行都是
    裸 QWidget。一旦给它上窗口底色，白色卡片里就会冒出一条条灰带
    （浅色主题下肉眼可见，实测踩过）。

    顶层裸 QWidget 窗口的底色由 QPalette 的 Window 角色提供。

    注意：断言要扫**整条选择器列表**。第一版只匹配「行首的 .QWidget」，
    于是 `QMainWindow, QDialog, .QWidget { background: ... }` 这种写法
    被逗号绕过去了 —— 反向验证时测试没报错，等于白写。
    """
    s = qss.build_qss(_theme(True))
    scoped = ("QFrame#card", "QFrame#aiCard", "QScrollArea")
    offenders = []
    for sel, body in _qss_rules(s):
        if ".QWidget" not in sel:
            continue
        if any(k in sel for k in scoped):
            # 卡片 / 面板 / 滚动区里的容器本来就该透明
            if "transparent" not in body:
                offenders.append((sel, "被限定在卡片/滚动区里，但底色不是 transparent"))
            continue
        if "background" in body:
            offenders.append((sel, "带背景色 → 卡片内部容器会被染成窗口底色"))
    assert offenders == [], f"`.QWidget` 规则有问题: {offenders}"

    # 卡片 / 面板内部的容器必须显式透明
    assert "QFrame#card .QWidget" in s
    assert "QFrame#aiCard .QWidget" in s


def test_scrollarea_does_not_blank_out_inputs():
    """滚动区里的透明化只能用 `.QWidget`，不能用 `QWidget`。

    `QWidget` 会匹配所有子类 —— 滚动区里的 QLineEdit / QComboBox
    会一起变透明，输入框就「没有底色」了。
    """
    s = qss.build_qss(_theme(True))
    assert "QScrollArea .QWidget" in s
    assert "QScrollArea > QWidget > QWidget" not in s


def test_icon_button_danger_has_base_rule():
    """danger 图标按钮必须有基础规则。

    第一版只写了 `#iconButtonDanger:hover`，没有基础规则 ——
    于是它退化去匹配通用 `QPushButton`（背景 #2D2D30、padding 撑出
    120x30），面板右上角的关闭按钮变成一块大灰块。
    """
    s = qss.build_qss(_theme(True))
    m = re.search(r"QPushButton#iconButtonDanger[^{]*\{(.*?)\}", s, re.S)
    assert m, "缺少 #iconButtonDanger 的基础规则"
    assert "background: transparent" in m.group(1)
    assert "border: none" in m.group(1)


def test_icon_button_size_not_fixed_by_qss():
    """图标按钮的尺寸由 Python 侧 setFixedSize 决定。

    QSS 的 min/max-width 会盖掉 setFixedSize，两边打架时按钮会突然
    变成另一个尺寸（且没有任何报错）。
    """
    from presentation.design.widgets import IconButton

    s = qss.build_qss(_theme(True))
    m = re.search(r"QPushButton#iconButton[^{]*\{(.*?)\}", s, re.S)
    assert m
    assert "max-width" not in m.group(1) and "min-width" not in m.group(1)

    _theme(True)
    btn = IconButton("close", "关闭", danger=True, size=24)
    assert btn.width() == 24 or btn.sizeHint().width() <= 24 + 4, \
        f"图标按钮尺寸被样式表带偏了: {btn.sizeHint()}"


def test_tomato_shows_work_duration_when_idle():
    """空闲时显示「将要专注多久」，而不是 00:00。

    计时器自身的 `formatted`（空闲 = 00:00）有它自己的测试，不动；
    这是对话框的显示层修正 —— 一只番茄钟停在 00:00 看起来像坏了。
    """
    from presentation.dialogs import TomatoDialog
    from tools.timer_tool import TomatoTimer

    _theme(True)
    timer = TomatoTimer()
    dlg = TomatoDialog(timer)
    dlg._refresh()
    assert dlg._time_label.text() == f"{timer.work_duration:02d}:00"
    assert timer.get_status()["formatted"] == "00:00", "计时器语义不该被改动"


def test_empty_state_hint_has_usable_width():
    """空状态引导文案要有合理的换行宽度。

    布局用了 AlignCenter，自动换行的 QLabel 会一路收缩到一行两三个字，
    把句子折得七零八落。
    """
    from presentation.design.widgets import EmptyState

    _theme(True)
    es = EmptyState("scroll", "还没有日志", "启动一段时间后回来看看，或点「刷新」重试。")
    assert es._hint.minimumWidth() >= 240
    assert es._hint.maximumWidth() <= 600


# ============================================================
# 8. 面板 / 对话框共用同一份样式表
# ============================================================

def test_panel_and_dialog_share_app_stylesheet():
    """「风格统一」是结构保证的：两边都直接用 theme().qss()。"""
    from presentation.ai_panel import AIPanel

    _theme(True)
    panel = AIPanel()
    assert panel.styleSheet() == theme().qss()


def test_panel_apply_theme_follows_theme_switch():
    from presentation.ai_panel import AIPanel

    _theme(False)
    panel = AIPanel()
    light_qss = panel.styleSheet()

    set_theme("dark", persist=False)
    panel.apply_theme()

    assert panel.styleSheet() != light_qss
    assert panel.styleSheet() == theme().qss()


def test_panel_toggle_theme_switches_and_emits():
    from presentation.ai_panel import AIPanel
    from presentation.theme import theme_name

    _theme(False)
    panel = AIPanel()
    seen = []
    panel.theme_changed.connect(seen.append)

    panel._on_toggle_theme()
    assert theme_name() == "dark"
    assert seen == ["dark"]

    panel._on_toggle_theme()
    assert theme_name() == "light"
    assert seen == ["dark", "light"]


def test_panel_is_topmost_and_tool():
    """面板要独立置顶（桌宠之外），且是 Tool 窗口（不占任务栏）。"""
    from PySide6.QtCore import Qt

    from presentation.ai_panel import AIPanel

    _theme(True)
    flags = AIPanel().windowFlags()
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint)
    assert bool(flags & Qt.WindowType.Tool)


def test_panel_has_raise_to_front():
    from presentation.ai_panel import AIPanel

    _theme(True)
    assert hasattr(AIPanel(), "raise_to_front")


# ============================================================
# 9. 图表与建议卡（P2.14）
# ============================================================

_CHART_KEYS = ("chart_work", "chart_study", "chart_comm", "chart_fun",
               "chart_other", "chart_idle", "chart_track")


def test_chart_palette_tokens_exist():
    """两套主题都必须有图表色 —— 缺一个就会在切主题时 KeyError。"""
    for dark in (True, False):
        pal = _theme(dark)
        for key in _CHART_KEYS:
            assert pal.has(key), (dark, key)


def test_chart_colors_differ_between_themes():
    """深浅两套的图表色必须真的不同，否则切主题时图表不跟着变。"""
    dark = _theme(True)
    dark_colors = [dark.color(k).name() for k in ("chart_work", "chart_idle")]
    light = _theme(False)
    light_colors = [light.color(k).name() for k in ("chart_work", "chart_idle")]
    assert dark_colors != light_colors


def test_chart_track_and_idle_visible_on_page_bg():
    """`chart_idle` / `chart_track` 必须与页面底色拉得开。

    这两个值都是**铺满一整条**的底色，一旦与页面底色接近就会「消失」：
      · `chart_idle` 是时间轴上没记录的那段 —— 消失后整条轴看起来像
        **只画到最后一个色块就断了**（第一次目检就是这么误读的）。
        它一度取成浅色 #F0F0EE / 深色 #2A2A2B，前者与 window(#F3F3F3) 只差
        3 级、后者**正好等于** surface_alt。
      · `chart_track` 是排行条的底槽 —— 消失后就分不清那条彩色条
        「占了多大比例」（浅色曾是 #ECECEC，与 window 只差 7 级）。

    这里按「最大单通道差值」判定，阈值 10 是「肉眼能看出有一条带」的下限。
    """
    def distance(a, b) -> int:
        return max(abs(a.red() - b.red()),
                   abs(a.green() - b.green()),
                   abs(a.blue() - b.blue()))

    for dark in (True, False):
        pal = _theme(dark)
        for token in ("chart_idle", "chart_track"):
            fill = pal.color(token)
            for bg in ("window", "surface", "surface_alt"):
                gap = distance(fill, pal.color(bg))
                assert gap >= 10, (
                    f"{'dark' if dark else 'light'}: {token} vs {bg} 只差 {gap}")


def test_chart_widgets_have_qss_rules():
    """新组件的 objectName 必须在 QSS 里有规则 —— 漏了会变成无样式裸控件。"""
    sheet = qss.build_qss(_theme(False))
    for name in ("statTile", "statTileLabel", "statTileValue",
                 "rankName", "rankValue",
                 "adviceCard", "adviceAccent", "adviceHeadline", "adviceEvidence",
                 "overviewBoard", "overviewTitle"):
        assert f"#{name}" in sheet, name


def test_category_color_token_mapping():
    from presentation.design.charts import category_color_token

    assert category_color_token("工作") == "chart_work"
    assert category_color_token("学习") == "chart_study"
    assert category_color_token("沟通") == "chart_comm"
    assert category_color_token("娱乐") == "chart_fun"
    assert category_color_token("其他") == "chart_other"
    assert category_color_token(None) == "chart_other"
    assert category_color_token("") == "chart_other"


def test_every_category_has_a_distinct_chart_color():
    """`CATEGORIES` 里每一类都必须有**专属**颜色，且互不重复。

    这是「图表配色」与「分类引擎」两处清单的**同步护栏**。v1.9.0 改分类体系
    （新增「学习」「娱乐」，删掉「浏览」）时漏改了 `charts._CATEGORY_TOKENS`，
    结果两类双双掉进 `chart_other` 灰色兜底 —— 时间轴上只剩三色，
    而**没有任何断言会红**（旧用例只钉了当时那四个名字）。

    所以这里不写死名单，直接遍历 `CATEGORIES`：
      · 除「其他」外，每一类都要映射到非兜底 token（「其他」本就是兜底色，
        它落到 DEFAULT 是**对的**，所以先把它排除掉，否则用例自己会永远红）；
      · 五类的 token 两两不同（两类共用一色 → 图上分不出来 → 当场红）。
    """
    from engine.activity.category import CATEGORIES, OTHER
    from presentation.design.charts import (
        DEFAULT_CATEGORY_TOKEN,
        category_color_token,
    )

    tokens = {cat: category_color_token(cat) for cat in CATEGORIES}

    assert tokens[OTHER] == DEFAULT_CATEGORY_TOKEN, "「其他」就该走兜底色"
    fell_back = {c: t for c, t in tokens.items()
                 if c != OTHER and t == DEFAULT_CATEGORY_TOKEN}
    assert not fell_back, f"这些类别掉进了兜底灰，没有专属配色: {fell_back}"
    assert len(set(tokens.values())) == len(CATEGORIES), (
        f"配色有重复（两类共用一色，图上分不出来）: {tokens}")


def test_stat_tile_shows_label_and_value():
    from presentation.design.charts import StatTile

    _theme(False)
    tile = StatTile("今日总时长", "7h30m")
    assert tile.label() == "今日总时长"
    assert tile.value() == "7h30m"
    tile.set_value("8h")
    assert tile.value() == "8h"


# ============================================================
# 概览仪表盘（P2.15）
#
# 为什么这一组要**抓像素**而不是只断言属性
#   这次改动的目的就是「让概览看起来不一样」。属性设对了但 QSS 没生效
#   （选择器写错 / 属性没重刷）是最容易漏的坏法，而且断言照样 PASS。
#   所以关键的几条都 show 出来抓像素。
# ============================================================

def _blend_over(top, bottom):
    """把半透明的 `top` 合成到不透明的 `bottom` 上（QSS 背景的算法）。"""
    from PySide6.QtGui import QColor

    a = top.alphaF()
    return QColor(
        round(top.red() * a + bottom.red() * (1 - a)),
        round(top.green() * a + bottom.green() * (1 - a)),
        round(top.blue() * a + bottom.blue() * (1 - a)),
    )


def _styled_theme(dark: bool):
    """切主题，并把 QSS **真的装到 QApplication 上**。

    抓像素前必须走这个，不能用 `_theme()`。原因：
    `_theme()` 里的 `reset_for_tests()` 会清空 `_installed_apps`，
    而 `set_theme()` 只对**已注册**的 app 重装 QSS（`theme._reapply`
    遍历 `_installed_apps`）。不调 `install()` 就等于什么都没装 ——
    抓到的像素是「没上过样式」的样子，断言会莫名其妙地红。
    """
    pal = _theme(dark)
    install(app)
    return pal


def _max_channel_diff(a, b) -> int:
    return max(abs(a.red() - b.red()), abs(a.green() - b.green()),
               abs(a.blue() - b.blue()))


def _region_colors(img, x0, x1, y0, y1):
    """取一块矩形区域里的所有像素色。"""
    return [img.pixelColor(x, y)
            for x in range(x0, x1, 2) for y in range(y0, y1, 2)]


def test_overview_board_keeps_tiles_in_order():
    """台面按加入顺序排列，并能按 key 取回 —— 页面回填靠这个接口。"""
    from presentation.design.charts import OverviewBoard, StatTile

    _theme(False)
    board = OverviewBoard("今日概览")
    a = StatTile("今日总时长", primary=True)
    b = StatTile("深度工作")
    board.add_tile("total", a, stretch=2)
    board.add_tile("focus", b)

    assert board.title() == "今日概览"
    assert board.tiles() == [a, b]
    assert board.tile("total") is a
    assert board.tile("focus") is b
    assert board.tile("nope") is None


def test_overview_board_has_an_accent_top_edge():
    """顶边那条 accent 线是「这块是重点」的唯一信号 —— 必须有，且是强调色。

    只断言 QSS 源码里写了 `border-top` 太弱（改成别的颜色照样过），
    所以直接 show 出来抓顶边的像素。
    """
    from presentation.design.charts import OverviewBoard

    pal = _styled_theme(False)
    board = OverviewBoard("今日概览")
    board.resize(400, 120)
    board.show()
    app.processEvents()

    img = board.grab().toImage()
    top = img.pixelColor(200, 1)
    assert _max_channel_diff(top, pal.color("accent")) < 20, (
        f"顶边不是强调色，取到 {top.name()}")
    assert _max_channel_diff(top, pal.color("panel")) > 60, (
        "顶边与台面底色太接近 —— 那条线根本看不见")


def test_primary_tile_is_visually_distinct_from_the_others():
    """头条数字那格必须和其余格子**看得出不一样**。

    这条是本次改动的核心：改之前四个格子长得一模一样（都是 surface_alt
    灰块，浅色主题下与页面底色只差 4 级），整页最该被看见的信息反而
    最不显眼。断言用像素 —— 属性对了但 QSS 没生效是最容易漏的坏法。
    """
    from presentation.design.charts import OverviewBoard, StatTile

    pal = _styled_theme(False)
    board = OverviewBoard("今日概览")
    board.add_tile("total", StatTile("今日总时长", "7 小时", primary=True), stretch=2)
    board.add_tile("focus", StatTile("深度工作", "4 小时"))
    board.resize(600, 140)
    board.show()
    app.processEvents()

    img = board.grab().toImage()
    expect = _blend_over(pal.color("accent_soft"), pal.color("panel"))
    y0, y1 = 40, img.height() - 16

    primary = _region_colors(img, 20, 120, y0, y1)
    normal = _region_colors(img, img.width() - 100, img.width() - 20, y0, y1)

    assert min(_max_channel_diff(c, expect) for c in primary) < 20, (
        "头条格没有铺上强调软底 —— 和别的格子分不出来")
    assert min(_max_channel_diff(c, expect) for c in normal) > 20, (
        "普通格也铺了强调软底 —— 那就没有重点了")


def test_a_tile_with_a_bigger_stretch_really_gets_more_width():
    """伸展因子必须真的变成宽度 —— 头条格「更宽」靠的就是它。

    和页面那条分工：页面那条断言「给对了伸展因子」，这条断言
    「伸展因子真的会变宽」。少了这条，把 `add_tile` 里的 stretch 丢掉
    也照样 PASS。
    """
    from presentation.design.charts import OverviewBoard, StatTile

    _theme(False)
    board = OverviewBoard("今日概览")
    wide = StatTile("今日总时长", "7 小时", primary=True)
    a = StatTile("深度工作", "4 小时")
    b = StatTile("最长应用", "VS Code")
    board.add_tile("total", wide, stretch=2)
    board.add_tile("focus", a)
    board.add_tile("top", b)
    board.resize(900, 140)
    board.show()
    app.processEvents()

    assert wide.width() > a.width(), (wide.width(), a.width())
    assert wide.width() > b.width(), (wide.width(), b.width())


def test_tile_without_an_icon_leaves_no_gap():
    """不传 icon 时必须把图标位**藏起来**，不能留一块空白 ——
    否则标签会被推右，几格之间对不齐。"""
    from presentation.design.charts import StatTile

    _theme(False)
    assert StatTile("无图标")._icon.isHidden() is True
    assert StatTile("有图标", icon_name="clock")._icon.isHidden() is False


def test_ratio_bar_clamps_ratio():
    from presentation.design.charts import RatioBar

    _theme(False)
    bar = RatioBar()
    bar.set_ratio(1.8)
    assert bar.ratio() == 1.0
    bar.set_ratio(-0.5)
    assert bar.ratio() == 0.0
    bar.set_ratio(0.42)
    assert abs(bar.ratio() - 0.42) < 1e-9


def test_rank_bar_computes_relative_ratios():
    from presentation.design.charts import RankBar

    _theme(False)
    rank = RankBar(limit=3)
    rank.set_items([
        {"label": "VS Code", "value": 100.0, "category": "工作"},
        {"label": "微信", "value": 50.0, "category": "沟通"},
    ])
    assert rank.row_count() == 2
    assert abs(rank._rows[0]._bar.ratio() - 1.0) < 1e-9
    assert abs(rank._rows[1]._bar.ratio() - 0.5) < 1e-9


def test_rank_bar_hides_unused_rows():
    from presentation.design.charts import RankBar

    _theme(False)
    rank = RankBar(limit=5)
    rank.set_items([{"label": "A", "value": 1.0}])
    assert rank.row_count() == 1


def test_rank_bar_handles_all_zero_values():
    """全 0 时不能除零。"""
    from presentation.design.charts import RankBar

    _theme(False)
    rank = RankBar(limit=2)
    rank.set_items([{"label": "A", "value": 0.0}, {"label": "B", "value": 0.0}])
    assert rank._rows[0]._bar.ratio() == 0.0


def test_timeline_bar_accepts_segments():
    from presentation.design.charts import TimelineBar

    _theme(False)
    bar = TimelineBar()
    bar.set_segments(
        [{"app": "a", "category": "工作", "start_at": 100, "end_at": 200}],
        start=0, end=86400,
    )
    assert bar.segment_count() == 1
    bar.set_segments([], start=0, end=86400)
    assert bar.segment_count() == 0


def test_bar_chart_accepts_data():
    from presentation.design.charts import BarChart

    _theme(False)
    chart = BarChart()
    chart.set_data([{"value": 1.0}, {"value": 2.0}], value_key="value", highlight=1)
    assert len(chart._rows) == 2


def _advice(headline="上午的深度工作被切成 4 段",
            evidence=("微信打断 9 次",), kind="focus", minutes=45):
    from engine.activity import Advice, AdviceAction

    label = f"开始 {minutes} 分钟专注" if kind == "focus" and minutes else ""
    return Advice(
        headline=headline, evidence=tuple(evidence),
        action=AdviceAction(kind=kind, minutes=minutes if kind == "focus" else 0,
                            label=label),
    )


def test_advice_card_renders_structured_advice():
    from presentation.design.advice_card import AdviceCard

    _theme(False)
    card = AdviceCard()
    card.set_advice(_advice())
    assert card.headline() == "上午的深度工作被切成 4 段"
    assert "微信打断 9 次" in card.evidence_text()
    assert card.action_visible() is True
    assert card.action_text() == "开始 45 分钟专注"
    assert card.action_minutes() == 45


def test_advice_card_hides_action_when_not_actionable():
    from presentation.design.advice_card import AdviceCard

    _theme(False)
    card = AdviceCard()
    card.set_advice(_advice(kind="none", minutes=0))
    assert card.action_visible() is False


def test_advice_card_hides_evidence_when_empty():
    from presentation.design.advice_card import AdviceCard

    _theme(False)
    card = AdviceCard()
    card.set_advice(_advice(evidence=()))
    assert card.evidence_visible() is False


def test_advice_card_emits_adopt_with_the_advice():
    """点动作按钮 → 发出 (Advice, "adopt")。

    为什么信号带的是 **Advice 对象**而不是分钟数：采纳要留痕
    （依据 / 上下文 / 影响范围，见 engine.activity.decision），
    而留痕需要结论与证据 —— 分钟数不够拼出这条记录。
    """
    from presentation.design.advice_card import AdviceCard

    _theme(False)
    card = AdviceCard()
    adv = _advice(minutes=25)
    card.set_advice(adv)
    seen = []
    card.decided.connect(lambda a, act: seen.append((a, act)))
    card._btn_action.click()
    assert seen == [(adv, "adopt")]


def test_advice_card_does_not_emit_when_not_actionable():
    from presentation.design.advice_card import AdviceCard

    _theme(False)
    card = AdviceCard()
    card.set_advice(_advice(kind="none", minutes=0))
    seen = []
    card.decided.connect(lambda a, act: seen.append((a, act)))
    card._btn_action.click()
    assert seen == []


def test_advice_card_emits_ignore_with_the_advice():
    from presentation.design.advice_card import AdviceCard

    _theme(False)
    card = AdviceCard()
    adv = _advice()
    card.set_advice(adv)
    seen = []
    card.decided.connect(lambda a, act: seen.append((a, act)))
    card._btn_ignore.click()
    assert seen == [(adv, "ignore")]


def test_advice_card_escapes_evidence_html():
    """证据来自模型，可能带 < > —— 不转义会被当富文本解析。"""
    from presentation.design.advice_card import AdviceCard

    _theme(False)
    card = AdviceCard()
    card.set_advice(_advice(evidence=("<b>不该加粗</b>",)))
    assert "&lt;b&gt;" in card.evidence_text()
    assert "<b>" not in card.evidence_text()


def test_advice_card_renders_all_evidence_lines():
    from presentation.design.advice_card import AdviceCard

    _theme(False)
    card = AdviceCard()
    card.set_advice(_advice(evidence=("第一条", "第二条", "第三条")))
    text = card.evidence_text()
    for item in ("第一条", "第二条", "第三条"):
        assert item in text


if __name__ == "__main__":
    passed = 0
    failed = []
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print(f"[PASS] {name}")
            except Exception as e:  # noqa: BLE001
                failed.append((name, e))
                print(f"[FAIL] {name}: {e}")
    print(f"\n{passed} 通过 / {len(failed)} 失败")
    if failed:
        sys.exit(1)
