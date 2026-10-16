# -*- coding: utf-8 -*-
"""glass_widgets **兼容垫片**的契约测试。

这个文件以前测的是旧「液态玻璃」设计语言（14px 红绿灯、38px 按钮、
20px 圆角……）。那套设计已经整体废弃，换成了 VS Code / Win11 取向的
`presentation/design/`，所以**旧的像素断言不再成立，也不该成立**。

现在它守的是另一件事 —— 垫片存在的唯一理由：
    `extensions/user/` 下的第三方插件按**老名字**导入这个模块。
    只要名字还在、构造不炸、行为映射正确，老插件不改一行代码就能
    用上新皮肤。所以这里断言的是「老 API 契约」，不是像素值。

真正的设计规格由 `tests/test_design.py` 守。

运行:
    python tests/test_glass_widgets.py
    pytest tests/test_glass_widgets.py -v
"""
import os
import sys
from pathlib import Path

# offscreen 平台：无显示环境也可渲染（必须在 QApplication 创建前设置）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QDialog

from presentation.design import reset_for_tests, set_theme, theme
from presentation.glass_widgets import (
    RADIUS,
    SPACING,
    STATUS_COLOR,
    GlassButton,
    GlassTheme,
    LiquidGlassButton,
    SegmentedSelector,
    SettingsButton,
    ThemeToggleButton,
    ToggleSwitch,
    TrafficLight,
    apply_dialog_style,
    build_card,
    lerp_color,
    paint_dialog_background,
)

app = QApplication.instance() or QApplication([])


def _theme(dark: bool = True):
    reset_for_tests()
    set_theme("dark" if dark else "light", persist=False)
    return theme()


def _render(widget) -> QImage:
    """把控件渲染成图像（尺寸>0 即视为渲染成功）。"""
    widget.resize(widget.sizeHint().expandedTo(widget.minimumSizeHint()))
    img = QImage(widget.size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    widget.render(img)
    return img


# ============================================================
# 1. 名字必须在（垫片的核心价值）
# ============================================================

def test_legacy_names_are_exported():
    """老插件会 `from presentation.glass_widgets import X`，一个都不能少。"""
    import presentation.glass_widgets as gw

    expected = [
        "GlassTheme", "lerp_color", "SPACING", "RADIUS", "STATUS_COLOR",
        "GlassButton", "LiquidGlassButton", "SegmentedSelector",
        "SettingsButton", "ThemeToggleButton", "TrafficLight", "ToggleSwitch",
        "apply_dialog_style", "paint_dialog_background", "build_card",
    ]
    missing = [n for n in expected if not hasattr(gw, n)]
    assert missing == [], f"垫片缺少老名字: {missing}"


def test_glass_theme_is_the_new_theme():
    """GlassTheme 就是新的 Theme —— 老代码 `theme.color(...)` 继续可用。"""
    from presentation.design.theme import Theme

    assert GlassTheme is Theme
    _theme(True)
    assert GlassTheme().color("primary").isValid()      # 老 token 名仍可解析
    assert GlassTheme().color("accent").isValid()


def test_legacy_spacing_and_radius_keys_exist():
    """老代码会取 RADIUS['dialog'] / SPACING['md']，键名必须保留。"""
    for key in ("sm", "md", "lg", "dialog"):
        assert key in RADIUS, f"RADIUS 缺少老键名 {key!r}"
    for key in ("xs", "sm", "md", "lg", "xl"):
        assert key in SPACING, f"SPACING 缺少老键名 {key!r}"


# ============================================================
# 2. 主题相关：必须跟着当前主题走
# ============================================================

def test_lerp_color():
    """纯函数，与主题无关。"""
    from PySide6.QtGui import QColor

    a, b = QColor("#000000"), QColor("#FFFFFF")
    mid = lerp_color(a, b, 0.5)
    # 255 * 0.5 = 127.5，四舍五入到 127 或 128 都算对
    assert abs(mid.red() - 127) <= 1
    assert mid.red() == mid.green() == mid.blue()
    assert lerp_color(a, b, 5.0) == b      # 上界夹紧
    assert lerp_color(a, b, -1.0) == a     # 下界夹紧


def test_status_color_follows_theme():
    """STATUS_COLOR 从「写死的色值」改成「按当前主题实时解析」。

    否则深浅两套主题会共用同一个色值 —— 浅色下对比度不够。
    """
    _theme(False)
    light = STATUS_COLOR["online"]
    _theme(True)
    dark = STATUS_COLOR["online"]
    assert light != dark, "STATUS_COLOR 没有跟随主题变化"
    for key in ("online", "offline", "warning", "info"):
        assert STATUS_COLOR[key].startswith("#")
    assert "online" in STATUS_COLOR
    assert STATUS_COLOR.get("nope", "fallback") == "fallback"


# ============================================================
# 3. 控件：老构造签名 + 行为映射
# ============================================================

def test_glass_button_variant_mapping():
    """`primary=True` 映射到强调变体；老签名里的 `theme=` 仍被接受。"""
    _theme(True)
    primary = GlassButton("确定", primary=True, theme=GlassTheme())
    secondary = GlassButton("取消", primary=False, theme=GlassTheme())
    assert primary.property("accent") == "true"
    assert secondary.property("accent") is None
    for w in (primary, secondary):
        assert not _render(w).isNull()


def test_liquid_glass_button_danger_mapping():
    _theme(True)
    btn = LiquidGlassButton("连接", primary=True, theme=GlassTheme())
    assert btn.property("accent") == "true"

    btn.set_danger(True)
    assert btn.property("variant") == "danger"
    assert btn.property("accent") is None

    btn.set_danger(False)
    assert btn.property("accent") == "true", "取消危险态应回到原来的强调变体"

    plain = LiquidGlassButton("普通", primary=False)
    plain.set_danger(True)
    plain.set_danger(False)
    assert plain.property("accent") is None, "非强调按钮取消危险态不该变成强调"

    assert LiquidGlassButton.BUTTON_HEIGHT > 0
    assert not _render(btn).isNull()


def test_traffic_light_renders():
    _theme(True)
    w = TrafficLight("#FF5F57", "#FF7B73")
    img = _render(w)
    assert img.width() > 0 and img.height() > 0
    assert not img.isNull()


def test_toggle_switch():
    _theme(True)
    w = ToggleSwitch("自动登录", checked=False, theme=GlassTheme())
    assert not w.isChecked()
    assert w.toggled                      # 信号存在
    assert not _render(w).isNull()
    w.setChecked(True)
    assert w.isChecked()


def test_segmented_selector_modes():
    _theme(True)
    w = SegmentedSelector(mode="auto", theme=GlassTheme())
    assert w.mode() == "auto"
    w.set_mode("light", animate=False)
    assert w.mode() == "light"
    assert not _render(w).isNull()

    # modes / labels 数量不一致要报错（老契约）
    try:
        SegmentedSelector(modes=["a", "b"], labels=["甲"], theme=GlassTheme())
        raise AssertionError("应抛出 ValueError")
    except ValueError:
        pass

    # 非法 mode 回落到第一个，而不是崩
    assert SegmentedSelector(mode="不存在").mode() == "light"


def test_settings_and_theme_buttons_follow_theme():
    """回归：ThemeToggleButton.refresh_theme 曾经自己调 set_icon，
    而 set_icon 又回调 refresh_theme → RecursionError。
    """
    _theme(False)
    gear = SettingsButton(theme=GlassTheme())
    toggle = ThemeToggleButton(dark=False, theme=GlassTheme())
    assert not _render(gear).isNull()
    assert not _render(toggle).isNull()

    # 图标必须反映**真实主题**，而不是构造参数
    assert toggle._icon_name == "moon"     # 浅色 → 月亮
    _theme(True)
    toggle.set_dark(True)                  # 老调用：现在等价于「重新同步」
    assert toggle._icon_name == "sun"      # 深色 → 太阳
    toggle.set_dark(False)                 # 传错值也不该跑偏
    assert toggle._icon_name == "sun"


# ============================================================
# 4. 对话框外观（老 API）
# ============================================================

def test_apply_dialog_style_returns_theme():
    """老代码会 `self._theme = apply_dialog_style(self)` 然后取色。"""
    _theme(True)
    dlg = QDialog()
    t = apply_dialog_style(dlg)
    assert t is theme()
    assert t.color("text").isValid()
    assert not paint_dialog_background(dlg, t) is True   # 不抛异常即可


def test_build_card_returns_card_and_layout():
    _theme(True)
    card, layout = build_card("分组标题")
    assert card is not None
    assert layout is not None
    assert layout.count() >= 1        # 标题已加进去


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
