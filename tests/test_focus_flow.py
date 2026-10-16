# -*- coding: utf-8 -*-
"""专注反馈链路的回归测试（P2.18）。

守三件事：
    · **时长真的传下去了**：`start("work", minutes=45)` 必须跑 45 分钟。
      P2.18 之前 `start()` 只认 `self.work_duration`，建议卡上的「45 分钟」
      点下去实际跑 25 分钟 —— 界面说的和做的不一致。
    · **环说的事只有一件**：托盘与球共用 `ring_view`，专注时改画本次专注。
      判定必须**全枚举**（关闭 / 进行中 / 达成 / 专注 / 专注暂停）——
      只测「进行中」的话，把专注态并进「达成」照样能过。
    · **倒计时卡有持续可见的载体**：运行中展开、暂停可分辨、结束收起。

运行:
    python dev_bootstrap.py -m pytest tests/test_focus_flow.py -q
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

app = QApplication.instance() or QApplication([])

from engine.activity.advice import Advice, AdviceAction  # noqa: E402
from engine.activity.decision import ACTION_ADOPT  # noqa: E402
from presentation.design import reset_for_tests, set_theme  # noqa: E402
from presentation.design.advice_card import AdviceCard, AdviceSummary  # noqa: E402
from presentation.design.focus_card import (  # noqa: E402
    FOCUS_ENTRY_ID,
    FocusCard,
    apply_phase,
    duration_text,
    focus_label,
    focus_title,
    format_clock,
)
from presentation.design.theme import theme  # noqa: E402
from presentation.design.ring import (  # noqa: E402
    STATE_ACTIVE,
    STATE_DONE,
    STATE_FOCUS,
    STATE_FOCUS_PAUSED,
    STATE_OFF,
    activity_state,
    ring_view,
)
from presentation.forms import OrbForm  # noqa: E402
from tools.timer_tool import TomatoTimer  # noqa: E402

reset_for_tests()
set_theme("light", persist=False)

#: 球的专注弧色 #FFB04C —— 只用来在像素里认出「这一段是专注进度」。
_ORB_FOCUS_RGB = (255, 176, 76)


# ---------------------------------------------------------------- 辅助

def _render(form) -> QImage:
    """把形态画到透明画布上（排除背景填充，见 test_appearance 同款理由）。"""
    img = QImage(form.size(), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    form.render(p, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
    p.end()
    return img


def _count_amber(img: QImage) -> int:
    """数琥珀色像素。

    判据用「红远大于蓝」而不是精确相等 —— 弧是抗锯齿画的，边缘必然有过渡色。
    蓝（76,194,255）与白（255,255,255）的红蓝差都是 0 或负，不会被误计。
    """
    r0, g0, b0 = _ORB_FOCUS_RGB
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if (c.alpha() > 150 and abs(c.red() - r0) < 40
                    and abs(c.green() - g0) < 50 and abs(c.blue() - b0) < 50):
                n += 1
    return n


def _img_signature(img: QImage) -> bytes:
    return bytes(img.constBits())


#: 给控件一个父窗口的宿主。无父的 `show()` 会把它变成**顶层窗口** ——
#: 离屏下不会崩，但会凭空多出真实窗口，测试之间的可见性判定会互相干扰。
_KEEPALIVE: list = []


def _host() -> QWidget:
    w = QWidget()
    _KEEPALIVE.append(w)
    return w


class _FakeTimer:
    """只实现球与卡片真正用到的那几个方法。"""

    def __init__(self, state="idle", progress=0.0, remaining=0):
        self.status = {
            "state": state, "progress": progress, "remaining": remaining,
            "formatted": format_clock(remaining), "type": "work",
        }

    def get_status(self):
        return dict(self.status)

    def is_running(self):
        return self.status["state"] == "running"

    def is_paused(self):
        return self.status["state"] == "paused"


# ================================================================
# 1. 番茄钟：这一次要跑多久
# ================================================================

class TestTimerDuration:
    """`start()` 的分钟数必须**真的生效**。"""

    def test_default_uses_the_configured_work_duration(self):
        t = TomatoTimer(work_duration=25)
        try:
            assert t.start("work") is True
            assert t.get_status()["total"] == 25 * 60
        finally:
            t.stop()

    def test_explicit_minutes_override_the_default(self):
        t = TomatoTimer(work_duration=25)
        try:
            assert t.start("work", minutes=45) is True
            assert t.get_status()["total"] == 45 * 60, (
                "分钟数被默认时长吃掉了 —— 按钮说 45，实际跑 25"
            )
        finally:
            t.stop()

    def test_illegal_minutes_fall_back_to_the_default(self):
        """0 / 负数 / 非数字都不是「跑 0 分钟」，而是「按设置来」。"""
        for bad in (0, -5, None, "", "abc", 3.7, float("nan")):
            t = TomatoTimer(work_duration=30)
            try:
                assert t.start("work", minutes=bad) is True, bad
                # 3.7 → int() 截断成 3，这是「给了合法数」的情形，不算回退
                expected = 3 * 60 if bad == 3.7 else 30 * 60
                assert t.get_status()["total"] == expected, bad
            finally:
                t.stop()

    def test_break_durations_ignore_the_minutes_argument(self):
        """`minutes` 只对 `work` 有意义 —— 休息时长不该被它带跑。"""
        t = TomatoTimer(work_duration=25, break_duration=5)
        try:
            t.start("break", minutes=45)
            assert t.get_status()["total"] == 5 * 60
        finally:
            t.stop()

    def test_a_second_session_can_use_a_different_length(self):
        t = TomatoTimer(work_duration=25)
        try:
            t.start("work", minutes=25)
            t.stop()
            t.start("work", minutes=90)
            assert t.get_status()["total"] == 90 * 60
        finally:
            t.stop()

    def test_stop_invalidates_the_current_round(self):
        """`stop()` 必须换号 —— 这是「停 → 再开」不出两倍速的前提。"""
        t = TomatoTimer(work_duration=25)
        try:
            t.start("work", minutes=25)
            before = t._epoch
            t.stop()
            assert t._epoch != before
        finally:
            t.stop()

    def test_a_stale_thread_exits_without_decrementing(self):
        """上一轮的线程不许扣新会话的秒数。

        旧线程在 `sleep(1)` 里睡着时用户点了「结束专注」又开了一轮，
        `_running` 会被新会话重新置真 —— 旧线程醒来以为「还在跑」，
        于是两个线程一起倒扣，倒计时跑成两倍速。
        P2.18 之前 `stop()` 只有番茄钟对话框能触发，很难撞上；
        加了「结束专注」按钮后「停 → 再开」是常规操作，不修就是必现。

        反向验证发现第一版是**假**的：`_timer_loop` 里有两处号检查
        （睡前一次、醒后一次），只删睡前那次，醒后那次照样拦得住。
        真正兜底的是**醒后**那次，所以下面这行的位置就是判据。
        """
        from tools.timer_tool import TimerState

        t = TomatoTimer(work_duration=25)
        t._running = True
        t._remaining_seconds = 100
        t._total_seconds = 1500
        t.state = TimerState.RUNNING

        stale = t._epoch
        t._epoch += 1                      # 假装新一轮已经把它取代了
        t._timer_loop(stale)               # 旧线程进来

        assert t._remaining_seconds == 100, "过期线程扣了新一轮的秒数"
        t.stop()


# ================================================================
# 2. 环语义：托盘与球共用一份判定
# ================================================================

class TestRingView:
    """`ring_view` 是环的**唯一**口径 —— 五种状态全枚举。"""

    def test_daily_states_match_the_old_activity_state(self):
        """不专注时必须与原来的三态判定完全一致（别顺手改了老语义）。"""
        for enabled, ratio in ((False, 0.0), (True, 0.0), (True, 0.5),
                               (True, 1.0), (True, 1.4)):
            state, value = ring_view(enabled=enabled, ratio=ratio)
            assert state == activity_state(enabled, ratio)
            assert value == max(0.0, min(1.0, ratio))

    def test_focus_replaces_the_daily_ring(self):
        """专注进行中 → 环改画**本次专注**，不是今日进度。

        输入刻意取「今日 90%、本次 20%」这种**非等距、方向相反**的组合：
        两边都取 0.5 的话，把两者接反了照样能过。
        """
        state, value = ring_view(enabled=True, ratio=0.9, focus_ratio=0.2)
        assert state == STATE_FOCUS
        assert value == 0.2, "环还在画今日进度 —— 用户会把它读成本次专注"

    def test_focus_wins_even_when_the_daily_goal_is_reached(self):
        """今日已达成也要让位给专注态 —— 否则环画满环、看不出专注进度。"""
        state, _ = ring_view(enabled=True, ratio=1.0, focus_ratio=0.3)
        assert state == STATE_FOCUS

    def test_focus_wins_even_when_collection_is_off(self):
        """采集关了但用户主动开了专注 —— 环仍要表达专注（那是他自己点的）。"""
        state, _ = ring_view(enabled=False, ratio=0.0, focus_ratio=0.3)
        assert state == STATE_FOCUS

    def test_paused_is_its_own_state(self):
        state, value = ring_view(enabled=True, ratio=0.9, focus_ratio=0.3,
                                 focus_paused=True)
        assert state == STATE_FOCUS_PAUSED
        assert value == 0.3

    def test_five_states_are_distinct(self):
        """五种状态两两不同 —— 合并任意两个都会让指示说谎。"""
        states = {
            ring_view(enabled=False, ratio=0.0)[0],
            ring_view(enabled=True, ratio=0.5)[0],
            ring_view(enabled=True, ratio=1.0)[0],
            ring_view(enabled=True, ratio=0.0, focus_ratio=0.5)[0],
            ring_view(enabled=True, ratio=0.0, focus_ratio=0.5, focus_paused=True)[0],
        }
        assert states == {STATE_OFF, STATE_ACTIVE, STATE_DONE,
                          STATE_FOCUS, STATE_FOCUS_PAUSED}

    def test_values_are_clamped(self):
        for bad, expected in ((-1.0, 0.0), (5.0, 1.0), ("x", 0.0), (None, 0.0)):
            _, value = ring_view(enabled=True, ratio=bad)
            assert value == expected, bad
            _, value = ring_view(enabled=True, ratio=0.0, focus_ratio=bad)
            assert value == expected, bad


# ================================================================
# 3. 悬浮球：环与图标跟着专注走
# ================================================================

class TestOrbFocusRing:
    def test_focus_switches_the_ring_and_switches_back(self):
        form = OrbForm()
        form.set_progress(0.9, True)
        assert form.progress() == (0.9, STATE_ACTIVE)

        form.set_focus(0.25)
        assert form.progress() == (0.25, STATE_FOCUS)

        form.set_focus(None)
        assert form.progress() == (0.9, STATE_ACTIVE), "结束后没回到今日进度"

    def test_paused_focus_is_reported(self):
        form = OrbForm()
        form.set_focus(0.4, paused=True)
        assert form.focus() == (0.4, True)
        assert form.progress()[1] == STATE_FOCUS_PAUSED

    def test_focus_paints_a_visibly_different_ring(self):
        """光把状态改对不算 —— 得**画出来**。"""
        form = OrbForm()
        form.set_progress(0.5, True)
        daily = _render(form)
        form.set_focus(0.5)
        focusing = _render(form)

        assert _count_amber(daily) == 0, "不专注时不该有琥珀像素"
        assert _count_amber(focusing) > 0, "专注态没画成琥珀色"
        assert _img_signature(daily) != _img_signature(focusing)

    def test_paused_is_dimmer_than_running(self):
        """暂停要能一眼看出来 —— 靠压暗，不靠换色（换色会被读成第三种状态）。"""
        form = OrbForm()
        form.set_focus(0.5)
        running = _render(form)
        form.set_focus(0.5, paused=True)
        paused = _render(form)

        assert _count_amber(running) > 0
        assert _count_amber(paused) == 0, "暂停态没压暗"
        assert _img_signature(running) != _img_signature(paused)

    def test_center_icon_follows_the_focus_state(self):
        """参数层：图标名要按状态给对（像素层抓不住「画的是哪个图标」）。"""
        form = OrbForm()
        form.set_state("idle")
        assert form._icon_name() == "paw"

        form.set_progress(1.0, True)              # 今日已达成
        assert form._icon_name() == "check"

        form.set_focus(0.5)                       # 专注中 —— 不能被「已达成」抢走
        assert form._icon_name() == "clock"

        form.set_focus(0.5, paused=True)
        assert form._icon_name() == "pause"

    def test_icon_change_reaches_the_canvas(self):
        """生效层：图标真的换了（不然上面那条只证明「算出了个名字」）。"""
        form = OrbForm()
        form.set_progress(1.0, True)
        done = _render(form)
        form.set_focus(0.5)
        assert _img_signature(done) != _img_signature(_render(form))

    def test_refresh_focus_reads_the_timer(self):
        form = OrbForm()
        form._timer = lambda: _FakeTimer("running", 0.3, 1000)
        form.refresh_focus()
        assert form.focus()[0] == 0.3

        form._timer = lambda: _FakeTimer("paused", 0.3, 1000)
        form.refresh_focus()
        assert form.focus() == (0.3, True)

        form._timer = lambda: _FakeTimer("finished", 1.0, 0)
        form.refresh_focus()
        assert form.focus()[0] is None, "计时结束后环必须回到今日进度"

    def test_refresh_focus_survives_a_broken_timer(self):
        """计时器是可选插件 —— 它坏了不能让球画不出来。"""
        form = OrbForm()
        form.set_progress(0.5, True)

        def _boom():
            raise RuntimeError("timer exploded")

        form._timer = _boom
        form.refresh_focus()                       # 不该抛
        assert form.progress()[1] == STATE_ACTIVE  # 保持现状

        form._timer = lambda: None                 # 插件没加载
        form.refresh_focus()
        assert form.focus()[0] is None


# ================================================================
# 4. 倒计时卡
# ================================================================

class TestFocusCard:
    def test_clock_format(self):
        assert format_clock(0) == "00:00"
        assert format_clock(59) == "00:59"
        assert format_clock(60) == "01:00"
        assert format_clock(25 * 60) == "25:00"
        assert format_clock(90 * 60) == "90:00"
        for bad in (None, -5, "abc", float("nan")):
            assert format_clock(bad) == "00:00", bad

    def test_hidden_while_idle(self):
        card = FocusCard(_host())
        assert card.is_active() is False
        assert card.state() == "idle"

    def test_expands_while_running(self):
        card = FocusCard(_host())
        card.update_from({"state": "running", "remaining": 754, "progress": 0.5})
        assert card.is_active() is True
        assert card.title_text() == "专注中"
        assert card.clock_text() == "12:34"
        assert card.bar_value() == 50
        assert card.button_visible("pause") is True
        assert card.button_visible("resume") is False
        assert card.button_visible("stop") is True

    def test_paused_swaps_the_buttons_and_the_tone(self):
        card = FocusCard(_host())
        card.update_from({"state": "running", "remaining": 600, "progress": 0.6})
        card.update_from({"state": "paused", "remaining": 600, "progress": 0.6})
        assert card.title_text() == "专注已暂停"
        assert card.button_visible("pause") is False
        assert card.button_visible("resume") is True
        assert card.property("paused") == "true"

        card.update_from({"state": "running", "remaining": 600, "progress": 0.6})
        assert card.property("paused") is None, "恢复后没把暂停配色摘掉"

    def test_the_paused_bar_changes_colour(self):
        """进度条**自己**也要挂 `paused` —— 只挂卡片上，`::chunk` 不变色。

        目检发现的：暂停时边框与时钟都变色了，进度条却还是强调色。
        原因是 `QFrame#focusCard[paused] QProgressBar#focusBar::chunk`
        这种「祖先属性 + 子控件子部件」的选择器在 Qt 上不可靠。

        分两层钉，少任何一层都会悄悄退回强调色（看起来像没暂停）：
          ① 属性真的挂在进度条自己身上；
          ② QSS 里确实有一条按这个属性改 chunk 颜色的规则。
        """
        from presentation.design import qss
        from presentation.design.theme import theme

        card = FocusCard(_host())
        card.update_from({"state": "running", "remaining": 600, "progress": 0.5})
        assert card._bar.property("paused") is None

        card.update_from({"state": "paused", "remaining": 600, "progress": 0.5})
        assert card._bar.property("paused") == "true"

        card.update_from({"state": "running", "remaining": 600, "progress": 0.5})
        assert card._bar.property("paused") is None, "恢复后没摘掉进度条的暂停属性"

        sheet = qss.build_qss(theme())
        assert 'QProgressBar#focusBar[paused="true"]::chunk' in sheet, (
            "QSS 里没有按 paused 属性改 chunk 颜色的规则 —— 属性挂了也不会变色"
        )

    def test_collapses_when_finished(self):
        card = FocusCard(_host())
        card.update_from({"state": "running", "remaining": 5, "progress": 0.99})
        card.update_from({"state": "finished", "remaining": 0, "progress": 1.0})
        assert card.is_active() is False

    def test_reports_state_changes_exactly_once(self):
        """`state_changed` 只在**变化**时发 —— 每秒发一次会刷爆页面状态行。"""
        card = FocusCard(_host())
        seen = []
        card.state_changed.connect(seen.append)

        assert card.update_from({"state": "running", "remaining": 10, "progress": 0.1}) is True
        assert card.update_from({"state": "running", "remaining": 9, "progress": 0.2}) is False
        assert card.update_from({"state": "paused", "remaining": 9, "progress": 0.2}) is True
        assert card.update_from({"state": "idle"}) is True
        assert seen == ["running", "paused", "idle"]

    def test_buttons_emit_requests_instead_of_touching_the_timer(self):
        """卡片只发请求，不自己动计时器 —— 否则它和页面会各改各的。"""
        card = FocusCard(_host())
        hits = []
        card.pause_requested.connect(lambda: hits.append("pause"))
        card.resume_requested.connect(lambda: hits.append("resume"))
        card.stop_requested.connect(lambda: hits.append("stop"))
        card._btn_pause.click()
        card._btn_resume.click()
        card._btn_stop.click()
        assert hits == ["pause", "resume", "stop"]

    def test_provider_drives_the_card(self):
        card = FocusCard(_host())
        card.set_status_provider(lambda: _FakeTimer("running", 0.5, 300).status)
        assert card.is_active() is True
        assert card.clock_text() == "05:00"

        card.set_status_provider(lambda: _FakeTimer("idle").status)
        assert card.is_active() is False

    def test_stopping_the_provider_collapses_the_card(self):
        card = FocusCard(_host())
        card.set_status_provider(lambda: _FakeTimer("running", 0.5, 300).status)
        card.set_status_provider(None)
        assert card.is_active() is False

    def test_a_broken_provider_does_not_crash_the_page(self):
        card = FocusCard(_host())

        def _boom():
            raise RuntimeError("timer exploded")

        card.set_status_provider(_boom)
        assert card.is_active() is False

    def test_garbage_progress_is_clamped(self):
        card = FocusCard(_host())
        for bad, expected in ((1.7, 100), (-2.0, 0), (float("nan"), 0),
                              ("x", 0), (None, 0)):
            card.update_from({"state": "running", "remaining": 60, "progress": bad})
            assert card.bar_value() == expected, bad


# ================================================================
# 5. 总结块
# ================================================================

class TestAdviceSummary:
    def test_empty_summary_collapses_the_whole_block(self):
        """空总结要**整块收起** —— 画个空框用户会以为生成失败了。"""
        block = AdviceSummary(_host())
        assert block.isHidden() is True
        assert block.has_summary() is False

        block.set_summary("今天 6 小时里深度工作只占 2 小时")
        assert block.isHidden() is False
        assert block.has_summary() is True
        assert block.summary() == "今天 6 小时里深度工作只占 2 小时"

    def test_clearing_it_again_hides_it(self):
        block = AdviceSummary(_host())
        block.set_summary("有内容")
        block.set_summary("")
        assert block.isHidden() is True
        assert block.has_summary() is False

    def test_whitespace_only_counts_as_empty(self):
        block = AdviceSummary(_host())
        block.set_summary("   \n  ")
        assert block.isHidden() is True


# ================================================================
# P2.19：专注入口的反馈口径
# ================================================================

def _advice(minutes: int = 45, headline: str = "上午被切成 4 段") -> Advice:
    return Advice(
        headline=headline,
        evidence=("切换 4 次",),
        action=AdviceAction(kind="focus", minutes=minutes,
                            label=f"开始 {minutes} 分钟专注"),
    )


class TestFocusLabel:
    """四个专注入口共用同一份文案 —— 同一状态不能有两个词。

    只测一个状态是**假测试**：把 running 与 paused 合并、或者漏掉 break
    分支，只要没测到就照样绿。所以这里全枚举（4 状态 × 2 类型）。
    """

    def test_idle_always_says_how_long(self):
        for minutes in (1, 25, 45, 90):
            assert focus_label("idle", minutes) == f"开始 {minutes} 分钟专注"

    def test_running_and_paused_have_their_own_words(self):
        assert focus_label("running") == "专注中…"
        assert focus_label("paused") == "已暂停"

    def test_break_is_a_different_word_from_focus(self):
        # 休息阶段写成「专注中」是旧 bug（P2.19 顺带修掉）
        assert focus_label("running", kind="break") == "休息中…"
        assert focus_label("paused", kind="break") == "休息已暂停"

    def test_finished_goes_back_to_the_start_label(self):
        # 一轮走完之后按钮要能再点一次，文案必须回到「开始」
        assert focus_label("finished", 25) == "开始 25 分钟专注"

    def test_an_unknown_state_is_treated_as_idle(self):
        assert focus_label("nonsense", 25) == "开始 25 分钟专注"

    def test_no_state_produces_an_empty_label(self):
        """全枚举：漏一个就会出现一个**没有字**的按钮。"""
        for state in ("idle", "running", "paused", "finished"):
            for kind in ("work", "break"):
                assert focus_label(state, 25, kind).strip()


class TestFocusTitle:
    """倒计时卡标题要说清「做什么」+「这一轮多长」。"""

    def test_idle_and_finished_have_no_title(self):
        assert focus_title("idle") == ""
        assert focus_title("finished") == ""

    def test_running_shows_how_long_this_round_is(self):
        # 建议卡承诺「开始 90 分钟专注」—— 卡里必须能核对到这个 90
        assert focus_title("running", "work", 90 * 60) == "专注中 · 90 分钟"

    def test_without_a_total_the_span_is_omitted(self):
        assert focus_title("running", "work", 0) == "专注中"

    def test_break_is_not_called_focus(self):
        assert focus_title("running", "break", 5 * 60) == "休息中 · 5 分钟"

    def test_paused_keeps_the_span(self):
        assert focus_title("paused", "work", 25 * 60) == "专注已暂停 · 25 分钟"


class TestDurationText:
    def test_reads_whole_minutes(self):
        assert duration_text(90 * 60) == "90 分钟"
        assert duration_text(25 * 60) == "25 分钟"

    def test_zero_and_garbage_become_empty(self):
        for bad in (0, None, "x", object()):
            assert duration_text(bad) == "", bad


class TestApplyPhase:
    def test_it_sets_and_clears_the_property(self):
        btn = QPushButton()
        apply_phase(btn, "running")
        assert btn.property("phase") == "running"
        apply_phase(btn, "idle")
        assert btn.property("phase") is None

    def test_the_property_is_not_called_focus(self):
        """`focus` 是 QWidget 的**内建 bool 属性** —— 拿它当样式钩子会被遮蔽。

        这条断言看着像在数一个字符串常量，其实钉的是一个真踩到的坑：
        `setProperty("focus", "running")` 之后 `property("focus")` 读回来是
        `False`（字符串转 bool 失败），于是 QSS 的 `[focus="running"]`
        **永远不匹配**，而且不报任何错、不影响任何其它测试。
        现象极具误导性：属性「设上了」、unpolish/polish 也调了、样式就是不变
        —— 看起来像层叠顺序或特异度问题。
        """
        btn = QPushButton()
        apply_phase(btn, "running")
        assert btn.property("phase") == "running"
        # 对照组：内建属性吞掉字符串值，无论怎么设都读不出 "running"
        btn.setProperty("focus", "running")
        assert btn.property("focus") != "running"


class TestFocusEntryIdIsSharedWithTheQss:
    """两个入口按钮共用一个 id，QSS 也认这个 id —— 三者必须同名。"""

    def test_the_qss_targets_the_shared_id(self):
        assert f"#{FOCUS_ENTRY_ID}" in theme().qss()

    def test_the_qss_selects_on_phase(self):
        qss = theme().qss()
        assert f'#{FOCUS_ENTRY_ID}[phase="running"]' in qss
        assert f'#{FOCUS_ENTRY_ID}[phase="paused"]' in qss
        # 反向：旧的失效写法不能留在里面（留着 = 一条永远不匹配的死规则）
        assert f"#{FOCUS_ENTRY_ID}[focus=" not in qss


class TestAdviceCardFocusState:
    """建议卡上的「开始专注」必须自己跟着状态变 —— P2.19 用户报的那个。"""

    def _card(self, minutes: int = 45) -> AdviceCard:
        card = AdviceCard(_host())
        card.set_advice(_advice(minutes))
        return card

    def test_idle_shows_the_advice_label(self):
        card = self._card(45)
        assert card.action_text() == "开始 45 分钟专注"
        assert card.action_enabled() is True
        assert card.focus_state() == "idle"

    def test_running_swaps_the_text_and_locks_the_button(self):
        card = self._card(45)
        card.set_focus_state("running")
        assert card.action_text() == "专注中…"
        assert card.action_enabled() is False

    def test_paused_swaps_the_text_too(self):
        card = self._card(45)
        card.set_focus_state("paused")
        assert card.action_text() == "已暂停"
        assert card.action_enabled() is False

    def test_going_back_to_idle_restores_the_label(self):
        card = self._card(45)
        card.set_focus_state("running")
        card.set_focus_state("idle")
        assert card.action_text() == "开始 45 分钟专注"
        assert card.action_enabled() is True

    def test_a_locked_button_really_cannot_start_another_session(self):
        """判据不是「看起来灰了」，而是**真的发不出信号**。

        只看 `isEnabled()` 会漏掉「槽里没拦、靠外观假装」的实现 ——
        那种实现在键盘回车 / 程序化 click 下照样会开第二轮。
        """
        card = self._card(45)
        seen: list = []
        card.decided.connect(lambda a, act: seen.append((a, act)))
        card.set_focus_state("running")
        card._btn_action.click()
        assert seen == []

    def test_the_button_can_fire_again_once_idle(self):
        card = self._card(45)
        seen: list = []
        card.decided.connect(lambda a, act: seen.append((a, act)))
        card._btn_action.click()
        assert len(seen) == 1
        assert seen[0][1] == ACTION_ADOPT, "动作按钮对应的是「采纳」这个决定"

    def test_the_phase_flag_drives_the_colour(self):
        card = self._card(45)
        card.set_focus_state("running")
        assert card._btn_action.property("phase") == "running"
        card.set_focus_state("idle")
        assert card._btn_action.property("phase") is None

    def test_the_action_button_carries_the_shared_id(self):
        card = self._card(45)
        assert card._btn_action.objectName() == FOCUS_ENTRY_ID

    def test_a_new_advice_keeps_the_current_focus_state(self):
        """专注在跑的时候重新渲染卡片 —— 新卡不能先亮着再被锁。"""
        card = self._card(45)
        card.set_focus_state("running")
        card.set_advice(_advice(25, headline="另一条"))
        assert card.action_text() == "专注中…"
        assert card.action_enabled() is False

    def test_a_non_actionable_advice_is_not_affected(self):
        """没有动作按钮的建议（`kind="none"`）不该被专注态弄出个空按钮。

        断言里必须带上**文案**：只看 `action_visible()` 是假测试 ——
        按钮早就被 `setVisible(False)` 收起来了，之后无论怎么改它的文案，
        「可见性」都不会变，改坏了照样绿。
        """
        card = AdviceCard(_host())
        card.set_advice(Advice(headline="多休息", evidence=("e",)))
        before = card.action_text()
        card.set_focus_state("running")
        assert card.action_visible() is False
        assert card.action_text() == before
