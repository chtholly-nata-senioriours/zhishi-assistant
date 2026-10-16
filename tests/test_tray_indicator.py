# -*- coding: utf-8 -*-
"""常驻指示（托盘进度环）的回归测试 —— P2.14 第 5 步。

守三件事：
    · **三态可分**：关闭 / 进行中 / 达成，在图标上必须看得出来是三种状态。
      尤其「关闭」不能画成「0 进度」—— 空环会被读成「今天一点没干」，
      而真相是「根本没在记录」，两件事对用户的含义完全不同。
    · **数字来自插件**：图标与悬停提示的数值必须真的来自 `focus_progress()`，
      不是托盘自己算的（口径只能有一处）。
    · **坏了不能带崩程序**：插件缺失 / 查库抛异常时静默降级成静态图标。
"""
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from presentation.design import reset_for_tests, set_theme  # noqa: E402
from presentation.tray_icon import (  # noqa: E402
    STATE_ACTIVE,
    STATE_DONE,
    STATE_OFF,
    TrayIcon,
    activity_state,
    activity_tooltip,
    progress_icon,
)

app = QApplication.instance() or QApplication([])
reset_for_tests()
set_theme("light", persist=False)

#: 两种任务栏底色 —— 托盘图标的真实背景由 Windows 决定，不是应用主题。
LIGHT_TASKBAR = "#F3F3F3"
DARK_TASKBAR = "#1F1F1F"


def _sig(icon) -> bytes:
    """图标的像素指纹 —— 用来断言「两种状态画出来的图确实不一样」。"""
    img = icon.pixmap(64, 64).toImage()
    return bytes(img.constBits())


def _ring_hits(icon, backdrop: str, threshold: int = 60) -> int:
    """把图标合成到任务栏底色上，数**环带**上有多少采样点看得出颜色。

    采两个半径：环中心线（画进度弧 / 灰环的地方）与外沿（画白描边的地方）。
    深浅两种任务栏各靠其中一个起作用，所以两个都要采 ——
    只看中心线的话，深色任务栏上「未完成的那段」会量成「看不见」。
    """
    canvas = QImage(64, 64, QImage.Format.Format_ARGB32)
    canvas.fill(QColor(backdrop))
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, icon.pixmap(64, 64))
    painter.end()

    bg = QColor(backdrop)
    hits = 0
    for radius in (26.5, 30.0):
        for k in range(24):
            angle = 2 * math.pi * k / 24
            x = int(round(32 + radius * math.sin(angle)))
            y = int(round(32 - radius * math.cos(angle)))
            if not (0 <= x < 64 and 0 <= y < 64):
                continue
            c = canvas.pixelColor(x, y)
            if max(abs(c.red() - bg.red()), abs(c.green() - bg.green()),
                   abs(c.blue() - bg.blue())) >= threshold:
                hits += 1
    return hits


# ---------------------------------------------------------------- 三态判定

class TestActivityState:
    def test_disabled_is_off(self):
        assert activity_state(False, 0.0) == STATE_OFF
        assert activity_state(False, 1.0) == STATE_OFF, "关掉采集就不该显示进度"

    def test_in_progress_is_active(self):
        assert activity_state(True, 0.0) == STATE_ACTIVE
        assert activity_state(True, 0.99) == STATE_ACTIVE

    def test_reaching_goal_is_done(self):
        """`>= 1.0` 而不是 `== 1.0` —— `ratio` 已经被夹到 1.0，
        但「刚好达标」和「超额完成」必须是同一个状态。"""
        assert activity_state(True, 1.0) == STATE_DONE
        assert activity_state(True, 3.0) == STATE_DONE


# ---------------------------------------------------------------- 悬停提示

class TestActivityTooltip:
    def test_disabled_says_so(self):
        text = activity_tooltip({"enabled": False, "focus": 0.0, "goal": 14400.0})
        assert "已关闭" in text
        assert "%" not in text, "没在记录就不该报百分比"

    def test_reports_focus_against_goal(self):
        text = activity_tooltip(
            {"enabled": True, "focus": 5400.0, "goal": 14400.0, "ratio": 0.375}
        )
        assert "1 小时 30 分" in text
        assert "4 小时" in text
        assert "38%" in text

    def test_goal_reached_is_announced(self):
        text = activity_tooltip(
            {"enabled": True, "focus": 15000.0, "goal": 14400.0, "ratio": 1.0}
        )
        assert "已达成目标" in text
        assert "4 小时 10 分" in text
        assert "%" not in text, "达成之后再说百分比没有意义"

    def test_zero_goal_does_not_divide(self):
        text = activity_tooltip({"enabled": True, "focus": 600.0, "goal": 0.0})
        assert "10 分钟" in text
        assert "%" not in text


# ---------------------------------------------------------------- 图标绘制

class TestProgressIcon:
    def test_draws_something(self):
        for state in (STATE_OFF, STATE_ACTIVE, STATE_DONE):
            assert not progress_icon(0.5, state).isNull(), state

    def test_off_is_not_the_same_picture_as_zero_progress(self):
        """这条是这一组的核心：「关闭」与「今天 0 进度」必须长得不一样。"""
        assert _sig(progress_icon(0.0, STATE_OFF)) != \
            _sig(progress_icon(0.0, STATE_ACTIVE))

    def test_arc_grows_with_ratio(self):
        assert _sig(progress_icon(0.0, STATE_ACTIVE)) != \
            _sig(progress_icon(0.5, STATE_ACTIVE))
        assert _sig(progress_icon(0.5, STATE_ACTIVE)) != \
            _sig(progress_icon(1.0, STATE_ACTIVE))

    def test_done_uses_a_different_colour_than_active(self):
        assert _sig(progress_icon(1.0, STATE_DONE)) != \
            _sig(progress_icon(1.0, STATE_ACTIVE))

    def test_absurd_ratio_is_clamped_not_crashed(self):
        """`ratio` 最后会被乘成 Qt 的「1/16 度」整数 —— 不夹的话天文数字
        或 `inf` 会让 shiboken 抛 `OverflowError`，把托盘图标画崩。

        注意这条**不是**在测「>1 会画满圆」：那是 Qt 自己的归一化行为
        （实测 span 450° / 540° / 900° 与 360° 画出来一模一样，
        所以那种断言改坏了也照样 PASS）。夹取在这里的真实作用只有一个 ——
        **别把越界的数喂给 C++ 的 int 参数**。
        """
        assert not progress_icon(1e12, STATE_ACTIVE).isNull()
        assert not progress_icon(float("inf"), STATE_ACTIVE).isNull()
        assert not progress_icon(-5.0, STATE_ACTIVE).isNull()

    def test_ring_reads_on_both_taskbar_colours(self):
        """三态在**浅色和深色任务栏**上都必须看得见。

        这条是 S14 目检逼出来的。环一开始取的是应用主题色，结果：
          · `light` 主题的 `text_disabled` 是 `#1F1F1F` —— 深色任务栏上整个消失；
          · `chart_track` 是 `#DCDCDC` —— 深色任务栏上被读成**满环**。
        托盘图标的底色是 Windows 任务栏给的，跟应用主题毫无关系，所以
        这里用「固定色 + 一圈白描边」：白描边管深色任务栏，深色底槽管浅色任务栏。
        断言的是「环带上确实有像素跟任务栏底色不一样」，两种底色都不能是 0。
        """
        for state, ratio in ((STATE_OFF, 0.0), (STATE_ACTIVE, 0.375),
                             (STATE_DONE, 1.0)):
            icon = progress_icon(ratio, state)
            for taskbar in (LIGHT_TASKBAR, DARK_TASKBAR):
                hits = _ring_hits(icon, taskbar)
                assert hits >= 12, (
                    f"{state} 在任务栏底色 {taskbar} 上只有 {hits} 个采样点"
                    f"看得出环 —— 这个状态下托盘图标基本是隐形的"
                )

    def test_icon_does_not_follow_the_app_theme(self):
        """托盘环的颜色**不跟应用主题走** —— 换主题前后必须逐像素一样。

        这条守的是 S14 那个 bug 的**结构性根因**。环一开始取的是主题色
        （进度弧 = `primary`，底槽 = `chart_track`，关闭态 = `text_disabled`），
        结果 `light` 主题的 `text_disabled = #1F1F1F` 在深色任务栏上整个消失。
        根因不是「选错了 token」，而是**根本不该问主题**：
        托盘图标的底色由 Windows 任务栏决定，跟应用主题没有关系。

        上一条断言「看得见」，这条断言「不随主题变」——
        两条合起来才把「固定色 + 白描边」这个设计钉住。

        三态都要过：`_TRAY_OFF` 只在关闭态才画，
        只测 `STATE_ACTIVE` 的话「关闭态读主题」这个 mutation 溜得过去。
        """
        try:
            for state, ratio in ((STATE_OFF, 0.0), (STATE_ACTIVE, 0.375),
                                 (STATE_DONE, 1.0)):
                set_theme("light", persist=False)
                before = _sig(progress_icon(ratio, state))
                set_theme("dark", persist=False)
                after = _sig(progress_icon(ratio, state))
                assert before == after, (
                    f"{state} 态下托盘环跟着应用主题变色了 ——"
                    f"深色任务栏上会糊掉或整个消失"
                )
        finally:
            set_theme("light", persist=False)

    def test_base_icon_is_kept_in_the_middle(self):
        """进度环套在**外圈**，中间的桌宠图标要留着 ——
        换成纯环的话用户在任务栏里认不出这是哪个程序。"""
        from PySide6.QtGui import QColor, QPixmap

        base_pm = QPixmap(64, 64)
        base_pm.fill(QColor("#FF00FF"))
        from PySide6.QtGui import QIcon

        with_base = _sig(progress_icon(0.5, STATE_ACTIVE, QIcon(base_pm)))
        without = _sig(progress_icon(0.5, STATE_ACTIVE))
        assert with_base != without, "传进来的底图没被画上去"
        # 正中间应当仍是底图颜色（进度环只占最外圈）
        img = progress_icon(0.5, STATE_ACTIVE, QIcon(base_pm)).pixmap(64, 64).toImage()
        center = img.pixelColor(32, 32)
        assert (center.red(), center.green(), center.blue()) == (255, 0, 255)


# ---------------------------------------------------------------- 接到托盘

class _StubPlugin:
    def __init__(self, progress, error=None):
        self._progress = dict(progress)
        self._error = error
        self.calls = []

    def focus_progress(self, days=1):
        self.calls.append(days)
        if self._error is not None:
            raise self._error
        return dict(self._progress)


class _PM:
    def __init__(self, plugin):
        self._plugin = plugin

    def get_plugin(self, name):
        return self._plugin if name == "activity_advisor" else None

    def get_all_plugins(self):
        return {}

    def get_menu_actions(self):
        return []


class _App:
    def __init__(self, plugin):
        self.plugin_manager = _PM(plugin)
        self.ui_manager = None


class TestTrayIndicator:
    def _tray(self, plugin):
        return TrayIcon(app=_App(plugin))

    def test_icon_and_tooltip_come_from_the_plugin(self):
        plugin = _StubPlugin(
            {"enabled": True, "focus": 5400.0, "goal": 14400.0, "ratio": 0.375}
        )
        tray = self._tray(plugin)
        assert plugin.calls == [1], "应当向插件要今天的进度"
        assert "1 小时 30 分" in tray._tray.toolTip()
        assert tray._progress_timer.isActive(), "没有定时刷新的话环永远不动"

    def test_disabled_state_reaches_the_tray(self):
        plugin = _StubPlugin({"enabled": False, "focus": 0.0,
                              "goal": 14400.0, "ratio": 0.0})
        tray = self._tray(plugin)
        assert "已关闭" in tray._tray.toolTip()

    def test_without_plugin_keeps_static_icon_and_no_timer(self):
        """没有活动插件时不该假装有进度 —— 保持原来的静态图标，也不起定时器。"""
        tray = self._tray(None)
        assert tray._tray.toolTip() == "知时助手"
        assert not tray._progress_timer.isActive()

    def test_query_failure_does_not_raise(self):
        """查库失败必须静默降级 —— 一个可选的常驻指示不该把程序带崩。"""
        plugin = _StubPlugin({}, error=RuntimeError("库坏了"))
        tray = self._tray(plugin)
        assert tray._tray.toolTip() == "知时助手"
        assert not tray._progress_timer.isActive()

    def test_refresh_is_idempotent(self):
        plugin = _StubPlugin(
            {"enabled": True, "focus": 60.0, "goal": 14400.0, "ratio": 1 / 240}
        )
        tray = self._tray(plugin)
        first = _sig(tray._tray.icon())
        tray.refresh_activity()
        assert _sig(tray._tray.icon()) == first
        assert plugin.calls == [1, 1]
