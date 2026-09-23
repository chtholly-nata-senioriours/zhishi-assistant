# -*- coding: utf-8 -*-
"""glass_widgets 冒烟测试：offscreen 平台下构造全部控件并渲染一帧。

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

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter

from presentation.glass_widgets import (
    GlassTheme, lerp_color,
    TrafficLight, ToggleSwitch, GlassButton, LiquidGlassButton,
    SegmentedSelector, SettingsButton, ThemeToggleButton,
)

app = QApplication.instance() or QApplication([])


def _render(widget) -> QImage:
    """把控件渲染成图像，返回图像（尺寸>0 即视为渲染成功）"""
    widget.resize(widget.sizeHint().expandedTo(widget.minimumSizeHint()))
    img = QImage(widget.size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    widget.render(img)
    return img


def test_lerp_color():
    a, b = GlassTheme().color("primary"), GlassTheme().color("primary_hover")
    mid = lerp_color(a, b, 0.5)
    assert mid.red() == round((a.red() + b.red()) / 2)
    # 边界夹紧
    assert lerp_color(a, b, 5.0) == b
    assert lerp_color(a, b, -1.0) == a


def test_theme():
    light, dark = GlassTheme(dark=False), GlassTheme(dark=True)
    assert light.color("text") != dark.color("text")
    dark.set_dark(False)
    assert dark.color("text") == light.color("text")


def test_traffic_light():
    w = TrafficLight("#FF5F57", "#FF7B73")
    img = _render(w)
    assert img.width() == 14 and img.height() == 14


def test_toggle_switch():
    theme = GlassTheme()
    w = ToggleSwitch("自动登录", checked=False, theme=theme)
    assert not w.isChecked()
    assert w.toggled  # signal 存在
    img = _render(w)
    assert img.width() > 58
    w.setChecked(True)
    assert w.isChecked()


def test_glass_button():
    theme = GlassTheme()
    primary = GlassButton("确定", primary=True, theme=theme)
    secondary = GlassButton("取消", primary=False, theme=theme)
    primary.setFocus()
    for w in (primary, secondary):
        img = _render(w)
        assert img.height() == 38
        assert not img.isNull()


def test_liquid_glass_button():
    theme = GlassTheme()
    btn = LiquidGlassButton("连接", primary=True, theme=theme)
    btn.set_danger(True)
    img = _render(btn)
    assert img.height() == LiquidGlassButton.BUTTON_HEIGHT
    assert not img.isNull()


def test_segmented_selector():
    theme = GlassTheme()
    w = SegmentedSelector(mode="auto", theme=theme)
    assert w.mode() == "auto"
    w.set_mode("light", animate=False)
    assert w.mode() == "light"
    assert not img_null(w)
    # 数量不一致应报错
    try:
        SegmentedSelector(modes=["a", "b"], labels=["甲"], theme=theme)
        raise AssertionError("应抛出 ValueError")
    except ValueError:
        pass


def img_null(w) -> bool:
    return _render(w).isNull()


def test_settings_and_theme_buttons():
    theme = GlassTheme()
    gear = SettingsButton(theme=theme)
    toggle = ThemeToggleButton(dark=False, theme=theme)
    toggle.set_dark(True)
    for w in (gear, toggle):
        img = _render(w)
        assert img.width() == 20 and img.height() == 20


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
