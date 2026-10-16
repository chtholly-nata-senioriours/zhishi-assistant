# -*- coding: utf-8 -*-
"""应用主题与「窗口风格统一」的回归测试。

背景（用户实测报的两个问题）
    1. 「关掉 AI 服务设置界面后整个应用都关掉了」——见 tests/test_window_lifecycle.py
    2. 「各个部分 ui 设计不统一」——面板写死一份深色 QSS，对话框固定浅色，
       点面板上的 ⚙ 会弹出一张白卡片盖在深色面板上。
       根因：`appearance.theme` 这个配置项**从来没有任何代码读过**。

现在的架构
    `presentation/design/` 是设计系统（tokens / theme / qss / icons / widgets），
    `presentation/theme.py` 只是老 API 的兼容门面。
    所有窗口**共用** `theme().qss()`，所以「风格一致」是结构上保证的，
    不是靠人工对齐数值。

运行:
    python tests/test_theme.py
    pytest tests/test_theme.py -v
"""
import os
import sys
from pathlib import Path

# offscreen 平台：无显示环境也能建窗口（必须在 QApplication 创建前设置）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from presentation.design import reset_for_tests
from presentation.design.theme import THEME_DARK, THEME_DEFAULT, THEME_LIGHT
from presentation.theme import (
    app_theme, is_dark, normalize_theme, set_theme, theme_name,
)

app = QApplication.instance() or QApplication([])


def _reset_theme_state():
    """清掉主题的进程级缓存，让每个用例从干净状态开始。

    theme 是刻意的单例（所有窗口必须共用同一个实例），
    所以测试里得手动重置 —— 这也提醒了：跨用例的状态是真实存在的。
    """
    reset_for_tests()


# ============================================================
# 1. 取值规整
# ============================================================

def test_normalize_theme_accepts_valid_values():
    assert normalize_theme("dark") == THEME_DARK
    assert normalize_theme("light") == THEME_LIGHT
    assert normalize_theme("default") == THEME_DEFAULT


def test_normalize_theme_is_case_and_space_insensitive():
    assert normalize_theme("  DARK  ") == THEME_DARK
    assert normalize_theme("Light") == THEME_LIGHT


def test_normalize_theme_falls_back_on_garbage():
    """配置是用户可手改的，一个错别字不该让 UI 崩。"""
    for bad in ("", "darkk", "blue", None, 123, "drak"):
        assert normalize_theme(bad) == THEME_DEFAULT


def test_is_dark_only_true_for_dark():
    assert is_dark("dark") is True
    assert is_dark("light") is False
    assert is_dark("default") is False
    assert is_dark(None) is False


def test_default_resolves_to_light():
    """规格参考 Windows 11 原生应用，default 落浅色。"""
    _reset_theme_state()
    set_theme(THEME_DEFAULT, persist=False)
    assert app_theme().name == THEME_LIGHT
    assert app_theme().dark is False


# ============================================================
# 2. 单例与切换
# ============================================================

def test_app_theme_is_singleton():
    """所有窗口必须拿到**同一个**实例，否则又会出现两套主题。"""
    _reset_theme_state()
    assert app_theme() is app_theme()


def test_set_theme_switches_in_place():
    """原地改（同一个对象），持有引用的自绘控件才能跟着变。"""
    _reset_theme_state()
    set_theme(THEME_LIGHT, persist=False)
    before = app_theme()

    set_theme(THEME_DARK, persist=False)

    assert app_theme() is before, "换主题不该换对象"
    assert before.dark is True
    assert theme_name() == THEME_DARK


def test_dark_and_light_palettes_match_the_spec():
    """规格钉死的两个主色：深 #252526 / 浅 #F3F3F3，强调 #4C8DFF / #0067C0。"""
    _reset_theme_state()
    set_theme(THEME_DARK, persist=False)
    assert app_theme().color("window").name().upper() == "#252526"
    assert app_theme().color("panel").name().upper() == "#1E1E1E"
    assert app_theme().color("accent").name().upper() == "#4C8DFF"

    set_theme(THEME_LIGHT, persist=False)
    assert app_theme().color("window").name().upper() == "#F3F3F3"
    assert app_theme().color("panel").name().upper() == "#FFFFFF"
    assert app_theme().color("accent").name().upper() == "#0067C0"


def test_theme_name_reflects_memory_not_config():
    """persist=False 时配置没动，但 theme_name() 必须报实际生效的值。"""
    _reset_theme_state()
    set_theme(THEME_DARK, persist=False)
    assert theme_name() == THEME_DARK


def test_set_theme_normalizes_invalid_input():
    _reset_theme_state()
    set_theme("这不是主题", persist=False)
    assert theme_name() == THEME_DEFAULT
    assert app_theme().dark is False


def test_theme_changed_signal_fires_only_on_real_change():
    """重复设同一个主题不该触发重绘 —— 否则每次保存设置都全窗口重刷。"""
    _reset_theme_state()
    set_theme(THEME_LIGHT, persist=False)

    seen = []
    app_theme().changed.connect(lambda: seen.append(1))

    set_theme(THEME_LIGHT, persist=False)
    assert seen == [], "同值不该发信号"

    set_theme(THEME_DARK, persist=False)
    assert seen == [1]


# ============================================================
# 3. 未知 token 必须报错（不静默返回黑色）
# ============================================================

def test_unknown_token_raises():
    """打错 token 名要立刻炸，而不是画出一片黑 —— 后者极难排查。"""
    _reset_theme_state()
    try:
        app_theme().color("no_such_token_xyz")
    except KeyError:
        return
    raise AssertionError("未知 token 应该抛 KeyError")


def test_legacy_token_aliases_resolve():
    """老代码（giwifi 插件）用的是 glass_widgets 的键名，必须还能用。"""
    _reset_theme_state()
    set_theme(THEME_DARK, persist=False)
    t = app_theme()
    assert t.color("primary").name() == t.color("accent").name()
    assert t.color("text_sec").name() == t.color("text_secondary").name()


# ============================================================
# 4. 对话框跟随应用主题（不再是写死的浅色）
# ============================================================

def test_dialog_uses_the_same_theme_object():
    """对话框与面板必须共用同一个 Theme 实例。"""
    from presentation.dialogs import AppDialog

    _reset_theme_state()
    set_theme(THEME_DARK, persist=False)
    dlg = AppDialog(title="深")
    assert dlg._theme is app_theme()

    set_theme(THEME_LIGHT, persist=False)
    assert dlg._theme is app_theme(), "换主题后对话框应看到新主题"


def test_dialog_is_frameless_and_topmost():
    """对话框必须与桌宠 / 面板同处置顶层。

    否则置顶的 AI 面板会永久压住设置对话框 —— 点也翻不上去。
    """
    from PySide6.QtCore import Qt

    from presentation.dialogs import AppDialog

    _reset_theme_state()
    dlg = AppDialog(title="层级")
    flags = dlg.windowFlags()
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint)
    assert bool(flags & Qt.WindowType.FramelessWindowHint)


def test_glass_dialog_is_app_dialog():
    """`GlassDialog` 是历史名字，第三方插件按它导入 —— 不能丢。"""
    from presentation.dialogs import AppDialog, GlassDialog

    assert GlassDialog is AppDialog


def test_message_dialog_buttons_confirm_on_the_right():
    """按钮顺序遵循平台习惯：次要动作在左、确定在右。"""
    from PySide6.QtWidgets import QMessageBox

    from presentation.dialogs import MessageDialog

    _reset_theme_state()
    dlg = MessageDialog(None, QMessageBox.Icon.Question, "确认", "继续吗？",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No)
    row = dlg.layout().itemAt(dlg.layout().count() - 1).layout()
    labels = [row.itemAt(i).widget().text()
              for i in range(row.count()) if row.itemAt(i).widget()]
    assert labels == ["否", "是"], f"按钮顺序应为「否 | 是」，实际 {labels}"


def test_message_box_is_topmost():
    """模态提示框也必须置顶。

    实测：设置对话框 `topmost=True`，而 `QMessageBox(parent=dialog)` 的
    `topmost=False` —— Qt 只把 parent 设为 owner，**不**继承置顶标志。
    于是「保存时配置不完整」这类提示框会被置顶的 AI 面板压住。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    from presentation.dialogs import _build_message_box

    _reset_theme_state()
    box = _build_message_box(None, QMessageBox.Icon.Warning, "标题", "内容")
    assert bool(box.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)


def test_message_box_topmost_survives_setWindowModality():
    """`QMessageBox.setWindowModality()` **会重置窗口标志**。

    这是个静默的坑：先设置顶、再设 modality，置顶位就被抹掉了，
    没有任何报错，只有「提示框被压住」这一个现象。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    from presentation.dialogs import _build_message_box

    _reset_theme_state()
    box = _build_message_box(None, QMessageBox.Icon.Warning, "t", "m")
    box.setWindowModality(Qt.WindowModality.WindowModal)
    assert bool(box.windowFlags() & Qt.WindowType.WindowStaysOnTopHint), \
        "setWindowModality 之后置顶位丢了 —— 检查 _build_message_box 里的设置顺序"


if __name__ == "__main__":
    _reset_theme_state()
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            passed += 1
            print(f"[PASS] {name}")
    print(f"\n{passed} 个用例全部通过")
