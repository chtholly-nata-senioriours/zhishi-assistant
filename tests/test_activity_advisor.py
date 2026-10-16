# -*- coding: utf-8 -*-
"""活动建议插件契约测试。

分五层，每层都对应一个「如果不测就会悄悄坏掉」的点：

    Store    —— 落盘与聚合；**隐私由表结构保证**（断言表里没有 title 列）
    Tracker  —— 分段语义：同应用不切段 / 排除应用 / 短段过滤
    Summary  —— 摘要格式与边界，以及**不把多余字段带出去**
    Advisor  —— 提示词必须明写「不要臆测」（摘要里没有标题，模型很容易编）
    插件/UI  —— 默认关闭不订阅；对话框只发信号

为什么 Store 那条「没有 title 列」值得单独立一个测试
    「不记录窗口标题」如果只是代码里的自觉，迟早有人为了「让建议更准」
    顺手加上。写成表结构断言之后，想加就得先删这个测试 —— 那是个
    显眼的动作，review 时跑不掉。
"""
import os
import sys
import time
import types
from pathlib import Path

import pytest

# offscreen：无显示环境也能建控件（必须在 QApplication 创建前设置）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from engine.activity import (  # noqa: E402
    ACTION_ADOPT,
    ACTION_FOCUS,
    ACTION_IGNORE,
    ACTION_NONE,
    ADVICE_JSON_SPEC,
    ALLOWED_FOCUS_MINUTES,
    DAY_SECONDS,
    DEFAULT_MERGE_GAP,
    HOURS_PER_DAY,
    MAX_ADVICES,
    MAX_EVIDENCE,
    WORK_CATEGORY,
    ADVISOR_PRESET,
    ADVISOR_SYSTEM_PROMPT,
    ActivityStore,
    ActivityTracker,
    Advice,
    AdviceAction,
    AdviceReport,
    advice_fingerprint,
    advice_to_text,
    build_advisor_prompt,
    build_summary,
    busiest_hour,
    category_totals,
    clock_hour,
    compare_periods,
    daily_totals,
    day_start,
    focus_seconds,
    hour_label,
    hour_of_day,
    hour_switches,
    human_duration,
    longest_focus_seconds,
    merge_segments,
    parse_advices,
    period_bounds,
    same_day,
    should_nudge,
    since_for_days,
    switch_count,
    system_idle_seconds,
    today_range,
    top_apps,
    total_seconds,
)

# 与 plugin_manager 走同一条加载路径，顺带验证「插件能被发现」
from extensions.plugin_manager import _import_plugin_class  # noqa: E402

_PLUGIN_NAME = "activity_advisor"
_PLUGIN_DIR = Path(__file__).resolve().parent.parent / "extensions" / "system" / _PLUGIN_NAME
ActivityAdvisorPlugin = _import_plugin_class(_PLUGIN_DIR, _PLUGIN_NAME)
_plugin_module = sys.modules.get(f"petdemo_plugins.{_PLUGIN_NAME}")

assert ActivityAdvisorPlugin is not None, "activity_advisor 插件加载失败"

# 对话框测试需要 QApplication 存在；offscreen 平台已在文件顶部设好。
# 用 instance() 兜底：其他测试文件可能已经建过，别重复建。
from PySide6.QtWidgets import QApplication  # noqa: E402

_qapp = QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- 夹具


@pytest.fixture
def store():
    s = ActivityStore(":memory:")
    yield s
    s.close()


def _seg(app, cat, start, end, rate=0):
    return {
        "app": app, "category": cat,
        "start_at": float(start), "end_at": float(end),
        "seconds": float(end - start), "key_rate": rate,
    }


def _fake_app(values=None):
    class _Cfg:
        def __init__(self, v):
            self._v = v

        def get(self, key, default=None):
            return self._v.get(key, default)

    class _App:
        def __init__(self, v):
            self.config = _Cfg(v)
            self.input_monitor = None
            self.ui_manager = None

    return _App(values or {})


class _FakeBus:
    """替掉 event_bus，只记录订阅关系，不真的分发。"""

    def __init__(self):
        self.subs = {}

    def subscribe(self, ev, cb):
        self.subs.setdefault(ev, []).append(cb)

    def unsubscribe(self, ev, cb):
        try:
            self.subs.get(ev, []).remove(cb)
            return True
        except ValueError:
            return False


# ---------------------------------------------------------------- Store


class TestStore:
    def test_add_and_read_back(self, store):
        store.add_segment("code.exe", "工作", 100.0, 200.0, key_rate=42)
        segs = store.segments_since(0)
        assert len(segs) == 1
        assert segs[0]["app"] == "code.exe"
        assert segs[0]["category"] == "工作"
        assert segs[0]["seconds"] == 100.0
        assert segs[0]["key_rate"] == 42

    def test_seconds_is_derived_not_trusted(self, store):
        """seconds 由起止算出 —— 调用方给不了「对不上」的数据。"""
        store.add_segment("a.exe", "其他", 100.0, 250.0)
        assert store.segments_since(0)[0]["seconds"] == 150.0

    def test_schema_has_no_place_to_store_titles(self, store):
        """**隐私红线**：表结构里不能有存标题 / 内容的地方。"""
        cols = {
            row[1].lower()
            for row in store._conn.execute("PRAGMA table_info(segments)")
        }
        for forbidden in ("title", "window_title", "content", "text",
                          "screenshot", "clipboard"):
            assert forbidden not in cols, f"segments 表不该有 {forbidden} 列"

    def test_segments_since_filters(self, store):
        store.add_segment("old.exe", "其他", 100.0, 200.0)
        store.add_segment("new.exe", "其他", 900.0, 1000.0)
        assert [s["app"] for s in store.segments_since(500)] == ["new.exe"]

    def test_totals_by_app_sorted_desc(self, store):
        store.add_segment("a.exe", "工作", 0.0, 100.0)
        store.add_segment("b.exe", "工作", 0.0, 300.0)
        totals = store.totals_by_app(0)
        assert [t["app"] for t in totals] == ["b.exe", "a.exe"]
        assert totals[0]["seconds"] == 300.0
        assert totals[0]["segments"] == 1

    def test_totals_by_category(self, store):
        store.add_segment("a.exe", "工作", 0.0, 100.0)
        store.add_segment("b.exe", "娱乐", 0.0, 60.0)
        store.add_segment("c.exe", "工作", 0.0, 40.0)
        got = {r["category"]: r["seconds"] for r in store.totals_by_category(0)}
        assert got == {"工作": 140.0, "娱乐": 60.0}

    def test_prune_drops_only_old(self, store):
        now = 1_000_000.0
        store.add_segment("old.exe", "其他", now - 10 * 86400, now - 10 * 86400 + 60)
        store.add_segment("new.exe", "其他", now - 60, now)
        assert store.prune(7, now=now) == 1
        assert [s["app"] for s in store.segments_since(0)] == ["new.exe"]

    def test_prune_zero_days_is_noop(self, store):
        """传 0 不能把库清空 —— 那是 clear() 的职责。"""
        store.add_segment("a.exe", "其他", 0.0, 10.0)
        assert store.prune(0) == 0
        assert store.count() == 1

    def test_clear_removes_everything(self, store):
        store.add_segment("a.exe", "其他", 0.0, 10.0)
        store.add_segment("b.exe", "其他", 0.0, 10.0)
        assert store.clear() == 2
        assert store.count() == 0


# ---------------------------------------------------------------- Tracker


class TestTracker:
    def test_same_app_does_not_split(self, store):
        """标题变了（换标签页 / 改文件名）但应用没变 —— 不该切成两段。"""
        t = ActivityTracker(store, clock=lambda: 0.0)
        t.record("code.exe", "工作", at=100.0)
        t.record("code.exe", "工作", at=160.0)
        t.flush(at=200.0)
        segs = store.segments_since(0)
        assert len(segs) == 1
        assert segs[0]["seconds"] == 100.0      # 100 -> 200

    def test_app_change_splits(self, store):
        t = ActivityTracker(store, clock=lambda: 0.0)
        t.record("code.exe", "工作", at=100.0)
        t.record("chrome.exe", "工作", at=200.0)
        t.flush(at=300.0)
        segs = store.segments_since(0)
        assert [s["app"] for s in segs] == ["code.exe", "chrome.exe"]
        assert segs[0]["seconds"] == 100.0
        assert segs[1]["seconds"] == 100.0

    def test_excluded_app_closes_without_opening(self, store):
        """被排除的应用：结束当前段，且**不**开新段（这段算未记录）。"""
        t = ActivityTracker(store, clock=lambda: 0.0, exclude_apps=["WeChat.exe"])
        t.record("code.exe", "工作", at=0.0)
        t.record("wechat.exe", "其他", at=100.0)     # 大小写不敏感
        assert t.current is None
        t.flush(at=200.0)
        segs = store.segments_since(0)
        assert [s["app"] for s in segs] == ["code.exe"]
        assert segs[0]["seconds"] == 100.0

    def test_short_segment_is_dropped(self, store):
        t = ActivityTracker(store, clock=lambda: 0.0, min_segment_seconds=5.0)
        t.record("a.exe", "其他", at=0.0)
        t.record("b.exe", "其他", at=2.0)        # a 只有 2s
        t.flush(at=4.0)                          # b 也只有 2s
        assert store.count() == 0

    def test_flush_uses_clock_for_open_segment(self, store):
        """一直没切窗口时，flush 用**当前时间**收尾（否则时长为 0）。"""
        t = ActivityTracker(store, clock=lambda: 500.0)
        t.record("code.exe", "工作", at=100.0)
        t.flush()
        assert store.segments_since(0)[0]["seconds"] == 400.0

    def test_key_rate_sampled_at_close(self, store):
        t = ActivityTracker(store, clock=lambda: 0.0, key_rate_provider=lambda: 77)
        t.record("code.exe", "工作", at=0.0)
        t.flush(at=100.0)
        assert store.segments_since(0)[0]["key_rate"] == 77

    def test_key_rate_provider_failure_is_swallowed(self, store):
        def boom():
            raise RuntimeError("炸")

        t = ActivityTracker(store, clock=lambda: 0.0, key_rate_provider=boom)
        t.record("code.exe", "工作", at=0.0)
        t.flush(at=100.0)                        # 不该抛出去
        assert store.segments_since(0)[0]["key_rate"] == 0

    def test_empty_app_closes_current(self, store):
        """拿不到进程名时按「未记录」处理，而不是塞进「其他」。"""
        t = ActivityTracker(store, clock=lambda: 0.0)
        t.record("code.exe", "工作", at=0.0)
        t.record("", "其他", at=100.0)
        assert t.current is None


# ---------------------------------------------------------------- Summary


class TestSummary:
    def test_human_duration(self):
        assert human_duration(45) == "45 秒"
        assert human_duration(600) == "10 分钟"
        assert human_duration(3600) == "1 小时"
        assert human_duration(7800) == "2 小时 10 分"

    def test_empty_input(self):
        assert "没有采集到" in build_summary([])

    def test_zero_duration_input(self):
        segs = [_seg("a.exe", "工作", 0, 0)]
        assert "不足以分析" in build_summary(segs)

    def test_mentions_app_category_and_duration(self):
        text = build_summary([_seg("code.exe", "工作", 0, 600)])
        assert "code.exe" in text
        assert "工作" in text
        assert "10 分钟" in text

    def test_top_apps_truncation(self):
        segs = [_seg(f"app{i}.exe", "工作", 0, 100 + i) for i in range(12)]
        text = build_summary(segs, top_apps=3)
        assert "其余 9 个应用" in text

    def test_reported_switch_count_is_a_real_switch_count(self):
        """摘要里「应用切换次数」必须真的是**切换次数**，不是段数。

        原来写的是 `len(segments)` —— 段数 = 切换次数 + 1，多日数据里还会
        把「昨天收尾 → 今天开工」算进去。模型据此说「你今天切换了 47 次」
        就多一次，而且是跨天的，用户对着自己的日程也看不出来。
        """
        segs = [
            _seg("code.exe", "工作", 0, 600),
            _seg("chrome.exe", "浏览", 600, 900),
            _seg("code.exe", "工作", 900, 1200),
        ]
        text = build_summary(segs)
        assert f"应用切换次数：{switch_count(segs)}" in text
        assert f"应用切换次数：{len(segs)}" not in text

    def test_longest_focus_groups_consecutive_work(self):
        """在编辑器和浏览器之间来回查资料，算作一整段专注。"""
        segs = [
            _seg("code.exe", "工作", 0, 600),
            _seg("chrome.exe", "工作", 600, 900),
            _seg("steam.exe", "娱乐", 900, 1000),     # 打断
            _seg("code.exe", "工作", 1000, 1300),
        ]
        assert longest_focus_seconds(segs) == 900.0

    def test_summary_does_not_leak_extra_fields(self):
        """即便分段里被人塞了 title，摘要也只读它需要的字段。"""
        segs = [{
            "app": "code.exe", "category": "工作",
            "start_at": 0.0, "end_at": 600.0, "seconds": 600.0, "key_rate": 0,
            "title": "机密文档.docx - Word",
        }]
        assert "机密文档" not in build_summary(segs)


# ---------------------------------------------------------------- Advisor


class TestAdvisor:
    def test_preset_identity(self):
        assert ADVISOR_PRESET.id == "activity_advisor"
        assert ADVISOR_PRESET.default_delivery == "panel"

    def test_prompt_forbids_guessing(self):
        """摘要里没有标题，模型很容易顺着应用名编内容 —— 必须写死这条。"""
        assert "不要臆测" in ADVISOR_SYSTEM_PROMPT
        text = build_advisor_prompt("应用统计：code.exe 2 小时")
        assert "不要臆测" in text
        assert "code.exe" in text

    def test_prompt_states_what_data_is_missing(self):
        """还要写明「数据里没有什么」，与 system prompt 双重保险。"""
        assert "窗口标题" in build_advisor_prompt("x")


# ---------------------------------------------------------------- 插件


class TestPlugin:
    def test_disabled_by_default(self):
        p = ActivityAdvisorPlugin()
        p.app = _fake_app({})
        assert p.on_load(p.app) is True
        assert p._enabled is False

    def test_disabled_never_subscribes(self, monkeypatch):
        bus = _FakeBus()
        monkeypatch.setattr(_plugin_module, "event_bus", bus)
        p = ActivityAdvisorPlugin()
        p.app = _fake_app({})
        p.on_load(p.app)
        p.on_ui_ready(p.app)
        assert bus.subs == {}, "默认关闭时不该订阅任何事件"
        assert p._tracker is None

    def test_enabled_subscribes_and_records(self, monkeypatch):
        bus = _FakeBus()
        monkeypatch.setattr(_plugin_module, "event_bus", bus)
        monkeypatch.setattr(
            _plugin_module, "ActivityStore", lambda: ActivityStore(":memory:")
        )
        p = ActivityAdvisorPlugin()
        p.app = _fake_app({"activity.enabled": True})
        p.on_load(p.app)
        p.on_ui_ready(p.app)

        assert "WINDOW_ACTIVE" in bus.subs
        bus.subs["WINDOW_ACTIVE"][0](
            {"data": {"process": "code.exe", "category": "工作"}}
        )
        assert p._tracker.current["app"] == "code.exe"

    def test_unload_unsubscribes(self, monkeypatch):
        bus = _FakeBus()
        monkeypatch.setattr(_plugin_module, "event_bus", bus)
        monkeypatch.setattr(
            _plugin_module, "ActivityStore", lambda: ActivityStore(":memory:")
        )
        p = ActivityAdvisorPlugin()
        p.app = _fake_app({"activity.enabled": True})
        p.on_load(p.app)
        p.on_ui_ready(p.app)
        p.on_unload()
        assert bus.subs.get("WINDOW_ACTIVE") == []
        assert p._tracker is None

    def test_menu_action_present(self):
        p = ActivityAdvisorPlugin()
        p.app = _fake_app({})
        assert "今日概览" in [a.name for a in p.get_menu_actions()]

    def test_menu_offers_a_start_focus_shortcut(self):
        """菜单里要能**直接开工**。

        常驻指示的作用是「环没走满时让人想起来专注一下」——
        如果那之后还得先开窗口、再找按钮，这条链路就断了。
        """
        p = ActivityAdvisorPlugin()
        p.app = _fake_app({})
        actions = p.get_menu_actions()
        assert [a.name for a in actions] == ["今日概览", "开始 45 分钟专注"]

        started = []
        p.start_focus = lambda minutes=25: started.append(minutes) or True
        actions[1].callback()
        assert started == [45]

    def test_menu_action_opens_today_page(self, monkeypatch):
        """托盘菜单打开的是控制中心的「今日」页，不是插件自己的对话框。

        P2.14 把「今日」做成主窗口一等页面后，插件再弹一个功能重复的
        对话框就是两个互不同步的孤岛 —— 菜单要跳到那一页。
        """
        import presentation.control_center as cc_module

        seen = {}

        class _Win:
            def goto(self, title):
                seen["title"] = title

        monkeypatch.setattr(cc_module, "open_control_center", lambda app=None: _Win())
        p = ActivityAdvisorPlugin()
        p.app = _fake_app({})
        p._dialog = None
        p._open()
        assert seen == {"title": "今日"}
        assert p._dialog is None, "不该再弹插件自己的对话框"

    def test_menu_action_falls_back_to_dialog(self, monkeypatch):
        """控制中心起不来时退回插件自己的对话框 —— 保证插件单独也能用。"""
        import presentation.control_center as cc_module

        def _boom(app=None):
            raise RuntimeError("UI 不可用")

        monkeypatch.setattr(cc_module, "open_control_center", _boom)
        p = ActivityAdvisorPlugin()
        p.app = _fake_app({})
        p.on_load(p.app)
        p._open()
        assert p._dialog is not None

    def test_clear_reports_when_not_collecting(self):
        p = ActivityAdvisorPlugin()
        p.app = _fake_app({})
        p.on_load(p.app)
        p._on_clear()          # 没有对话框也不该抛


# ---------------------------------------------------------------- 对话框


class TestDialog:
    @staticmethod
    def _make(**kw):
        from petdemo_plugins.activity_advisor.dialog import ActivityAdvisorDialog
        return ActivityAdvisorDialog(**kw)

    def test_emits_analyze_with_selected_days(self):
        dlg = self._make(target_label="api.example.com", enabled=True)
        got = []
        dlg.analyze_requested.connect(got.append)
        dlg._btn_analyze.click()
        assert got == [7]                       # 默认近 7 天
        dlg.deleteLater()

    def test_disabled_state_blocks_analyze(self):
        dlg = self._make(enabled=False)
        assert dlg._btn_analyze.isEnabled() is False
        assert "关闭" in dlg._overview.toPlainText()
        dlg.deleteLater()

    def test_privacy_label_names_target_and_limits(self):
        dlg = self._make(target_label="api.deepseek.com", enabled=True)
        text = dlg._privacy.text()
        assert "api.deepseek.com" in text
        assert "窗口标题" in text
        dlg.deleteLater()

    def test_range_change_emits_days(self):
        dlg = self._make(enabled=True)
        got = []
        dlg.range_changed.connect(got.append)
        dlg._combo_days.setCurrentIndex(0)
        assert got == [1]
        dlg.deleteLater()


# ================================================================
# P2.13 增量：自然日 / 空闲 / 收工小结时机 / 建议缓存 / 页面
# ================================================================


def _local_ts(y, m, d, hh, mm=0):
    """构造一个**本地时区**的时间戳（测试里不要用 UTC 心算）。"""
    return time.mktime((y, m, d, hh, mm, 0, 0, 0, -1))


# ---------------------------------------------------------------- Schedule


class TestSchedule:
    """自然日语义 —— 「今天」必须是今天 00:00，不是 24 小时前。"""

    def test_day_start_is_midnight(self):
        ts = _local_ts(2026, 10, 13, 15, 30)
        ds = day_start(ts)
        lt = time.localtime(ds)
        assert (lt.tm_hour, lt.tm_min, lt.tm_sec) == (0, 0, 0)
        assert (lt.tm_year, lt.tm_mon, lt.tm_mday) == (2026, 10, 13)

    def test_since_for_one_day_is_today_not_24h_ago(self):
        ts = _local_ts(2026, 10, 13, 15, 30)
        assert since_for_days(1, ts) == day_start(ts)
        # 反面：如果实现成滚动 24 小时，起点会比今天 00:00 早 15.5 小时
        assert since_for_days(1, ts) > ts - 86400

    def test_since_for_seven_days_covers_seven_calendar_days(self):
        ts = _local_ts(2026, 10, 13, 9, 0)
        start = since_for_days(7, ts)
        assert start == day_start(ts) - 6 * 86400
        lt = time.localtime(start)
        assert (lt.tm_mon, lt.tm_mday) == (10, 7)

    def test_since_clamps_zero_and_negative(self):
        ts = _local_ts(2026, 10, 13, 9, 0)
        assert since_for_days(0, ts) == day_start(ts)
        assert since_for_days(-5, ts) == day_start(ts)

    def test_same_day(self):
        a = _local_ts(2026, 10, 13, 0, 1)
        b = _local_ts(2026, 10, 13, 23, 59)
        c = _local_ts(2026, 10, 14, 0, 1)
        assert same_day(a, b) is True
        assert same_day(b, c) is False

    def test_today_range_is_one_day(self):
        ts = _local_ts(2026, 10, 13, 12, 0)
        start, end = today_range(ts)
        assert end - start == 86400.0
        assert start == day_start(ts)

    def test_clock_hour_matches_localtime(self):
        ts = _local_ts(2026, 10, 13, 18, 45)
        assert clock_hour(ts) == 18


# ---------------------------------------------------------------- Idle


class TestIdle:
    """空闲探针必须「宁可返回 0 也不抛异常」—— 抛了会把采集一起带崩。"""

    def test_returns_non_negative_float(self):
        v = system_idle_seconds()
        assert isinstance(v, float)
        assert v >= 0.0

    def test_non_windows_returns_zero(self, monkeypatch):
        import engine.activity.idle as idle_mod

        monkeypatch.setattr(idle_mod, "sys", types.SimpleNamespace(platform="linux"))
        assert idle_mod.system_idle_seconds() == 0.0

    def test_probe_failure_falls_back_to_zero(self, monkeypatch):
        import engine.activity.idle as idle_mod

        monkeypatch.setattr(idle_mod, "sys", types.SimpleNamespace(platform="win32"))
        # 一个没有 windll / sizeof 的对象：任何属性访问都会炸
        monkeypatch.setattr(idle_mod, "ctypes", object())
        assert idle_mod.system_idle_seconds() == 0.0


# ---------------------------------------------------------------- Reminder


class TestReminder:
    """收工小结时机 —— 每条免打扰分支都单独锁住。"""

    #: 一个「什么都满足」的基准场景：19 点、有数据、没人挡着。
    BASE = dict(
        enabled=True,
        nudge_enabled=True,
        nudge_hour=18,
        last_nudged_at=None,
        has_data_today=True,
        fullscreen=False,
        timer_running=False,
        away=False,
    )

    def _check(self, **over):
        kw = dict(self.BASE)
        kw.update(over)
        kw.setdefault("now", _local_ts(2026, 10, 13, 19, 0))
        return should_nudge(**kw)

    def test_all_clear_returns_true(self):
        ok, reason = self._check()
        assert ok is True
        assert reason == "可以提醒"

    def test_disabled_collection_blocks(self):
        assert self._check(enabled=False)[0] is False

    def test_user_turned_off_nudges(self):
        ok, reason = self._check(nudge_enabled=False)
        assert ok is False
        assert "关闭" in reason

    def test_fullscreen_is_do_not_disturb(self):
        ok, reason = self._check(fullscreen=True)
        assert ok is False
        assert "全屏" in reason

    def test_focus_timer_is_do_not_disturb(self):
        ok, reason = self._check(timer_running=True)
        assert ok is False
        assert "专注" in reason

    def test_away_is_do_not_disturb(self):
        assert self._check(away=True)[0] is False

    def test_no_data_today_blocks(self):
        assert self._check(has_data_today=False)[0] is False

    def test_before_nudge_hour_blocks(self):
        ok, reason = self._check(now=_local_ts(2026, 10, 13, 17, 30))
        assert ok is False
        assert "18" in reason

    def test_once_per_day(self):
        # 今天已经提醒过
        ok, reason = self._check(last_nudged_at=_local_ts(2026, 10, 13, 18, 30))
        assert ok is False
        assert "已经提醒过" in reason
        # 昨天提醒过 → 今天照常
        assert self._check(last_nudged_at=_local_ts(2026, 10, 12, 18, 30))[0] is True

    def test_reason_is_always_returned(self):
        """原因永远有值 —— 出问题时看日志就知道被哪条挡下的。"""
        for over in ({}, {"enabled": False}, {"away": True}):
            ok, reason = self._check(**over)
            assert isinstance(reason, str) and reason


# ---------------------------------------------------------------- 建议缓存


class TestAdviceCache:
    def test_save_and_read_back(self, store):
        store.save_advice("day", "3:120:0:120", "早点休息", now=1000.0)
        row = store.get_advice("day")
        assert row["text"] == "早点休息"
        assert row["signature"] == "3:120:0:120"
        assert row["created_at"] == 1000.0

    def test_missing_returns_none(self, store):
        assert store.get_advice("week") is None

    def test_scope_keeps_latest_only(self, store):
        store.save_advice("day", "a", "第一版")
        store.save_advice("day", "b", "第二版")
        assert store.get_advice("day")["text"] == "第二版"
        assert store.count_advices() == 1

    def test_scopes_are_independent(self, store):
        store.save_advice("day", "a", "日报")
        store.save_advice("week", "b", "周报")
        assert store.get_advice("day")["text"] == "日报"
        assert store.get_advice("week")["text"] == "周报"

    def test_clear_wipes_advices_too(self, store):
        """「清空行为数据」要清干净 —— 建议文本是根据用户活动生成的。"""
        store.add_segment("a.exe", "工作", 0.0, 100.0)
        store.save_advice("day", "x", "昨天你工作了很久")
        assert store.clear() == 1
        assert store.count() == 0
        assert store.get_advice("day") is None

    def test_clear_advices_keeps_segments(self, store):
        store.add_segment("a.exe", "工作", 0.0, 100.0)
        store.save_advice("day", "x", "建议")
        assert store.clear_advices() == 1
        assert store.count() == 1

    def test_segments_between_excludes_next_day(self, store):
        store.add_segment("a.exe", "工作", 0.0, 100.0)
        store.add_segment("b.exe", "工作", 200.0, 300.0)
        got = store.segments_between(0.0, 200.0)
        assert [s["app"] for s in got] == ["a.exe"]

    def test_meta_roundtrip(self, store):
        assert store.get_meta("k") is None
        store.set_meta("k", "1.5")
        assert store.get_meta("k") == "1.5"
        store.set_meta("k", "2.5")
        assert store.get_meta("k") == "2.5"


# ---------------------------------------------------------------- 空闲剪裁


class TestTrackerIdle:
    """空闲信号只做一件事：把「人不在」的时间从段里剪掉。"""

    def test_idle_time_is_trimmed_off_the_end(self, store):
        t = ActivityTracker(store, idle_provider=lambda: 600.0)
        t.record("code.exe", "工作", at=0.0)
        t.record("chrome.exe", "工作", at=1800.0)
        segs = store.segments_since(0)
        assert len(segs) == 1
        # 30 分钟里有 10 分钟人不在 → 只记 20 分钟
        assert segs[0]["seconds"] == 1200.0

    def test_segment_fully_inside_idle_is_dropped(self, store):
        t = ActivityTracker(store, idle_provider=lambda: 600.0)
        t.record("code.exe", "工作", at=0.0)
        t.flush(at=300.0)
        assert store.count() == 0

    def test_without_idle_provider_duration_is_untouched(self, store):
        t = ActivityTracker(store)
        t.record("code.exe", "工作", at=0.0)
        t.flush(at=1800.0)
        assert store.segments_since(0)[0]["seconds"] == 1800.0

    def test_probe_failure_does_not_trim(self, store):
        def boom():
            raise RuntimeError("probe down")

        t = ActivityTracker(store, idle_provider=boom)
        t.record("code.exe", "工作", at=0.0)
        t.flush(at=1800.0)
        assert store.segments_since(0)[0]["seconds"] == 1800.0

    def test_tick_closes_while_away(self, store):
        idle = {"v": 0.0}
        t = ActivityTracker(store, idle_provider=lambda: idle["v"], away_seconds=300.0)
        t.record("code.exe", "工作", at=0.0)
        idle["v"] = 600.0
        assert t.tick(at=1800.0) is True
        assert t.current is None
        assert store.segments_since(0)[0]["seconds"] == 1200.0

    def test_tick_resumes_after_returning(self, store):
        idle = {"v": 0.0}
        t = ActivityTracker(store, idle_provider=lambda: idle["v"], away_seconds=300.0)
        t.record("code.exe", "工作", at=0.0)
        idle["v"] = 7200.0
        t.tick(at=7200.0)                       # 离开 2 小时
        assert t.current is None
        idle["v"] = 0.0
        assert t.tick(at=7200.0) is False       # 回来了
        assert t.current is not None
        assert t.current["app"] == "code.exe"   # 续上离开前的应用

    def test_is_away_threshold(self, store):
        idle = {"v": 100.0}
        t = ActivityTracker(store, idle_provider=lambda: idle["v"], away_seconds=300.0)
        assert t.is_away() is False
        idle["v"] = 400.0
        assert t.is_away() is True


# ---------------------------------------------------------------- 插件（P2.13）


class _Cfg:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.saved = 0

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def save(self):
        self.saved += 1
        return True


class _App:
    def __init__(self, values=None):
        self.config = _Cfg(values)
        self.input_monitor = None
        self.ui_manager = None
        self.tray_icon = None
        self.timer = None


def _quiet_plugin(monkeypatch, values=None):
    """建一个已加载、已开始采集的插件，并把环境探针全部钉死。"""
    bus = _FakeBus()
    monkeypatch.setattr(_plugin_module, "event_bus", bus)
    monkeypatch.setattr(
        _plugin_module, "ActivityStore", lambda: ActivityStore(":memory:")
    )
    p = ActivityAdvisorPlugin()
    p.app = _App(values)
    p.on_load(p.app)
    # 这三个探针会碰真实系统（空闲 / 前台窗口 / 番茄钟），测试里必须钉死
    monkeypatch.setattr(p, "_idle", lambda: 0.0)
    monkeypatch.setattr(p, "_is_fullscreen", lambda: False)
    monkeypatch.setattr(p, "_is_timer_running", lambda: False)
    return p, bus


class TestPluginP213:
    def test_enabled_subscribes_tick(self, monkeypatch):
        p, bus = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        assert "TIME_TICK" in bus.subs, "收工小结靠 TIME_TICK 驱动"
        assert "WINDOW_ACTIVE" in bus.subs

    def test_set_enabled_starts_and_stops_immediately(self, monkeypatch):
        """一键开关必须**立即生效** —— 重启才生效的开关等于没做。"""
        p, bus = _quiet_plugin(monkeypatch, {"activity.enabled": False})
        p.on_ui_ready(p.app)
        assert bus.subs == {}

        assert p.set_enabled(True) is True
        assert p.is_enabled() is True
        assert p._tracker is not None
        assert "TIME_TICK" in bus.subs
        assert p.app.config.get("activity.enabled") is True
        assert p.app.config.saved == 1

        assert p.set_enabled(False) is True
        assert p.is_enabled() is False
        assert p._tracker is None
        assert bus.subs.get("WINDOW_ACTIVE") == []
        assert bus.subs.get("TIME_TICK") == []

    def test_overview_degrades_when_disabled(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {})
        p.on_ui_ready(p.app)
        assert "采集未开启" in p.overview(1)

    def test_generate_refuses_when_disabled(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {})
        p.on_ui_ready(p.app)
        assert "采集未开启" in p.generate(1)

    def test_scope_mapping(self):
        assert ActivityAdvisorPlugin._scope_for(1) == "day"
        assert ActivityAdvisorPlugin._scope_for(3) == "week"
        assert ActivityAdvisorPlugin._scope_for(7) == "week"

    def test_zero_valued_config_is_respected(self):
        """`0` 是合法配置值 —— 不能被 `or default` 悄悄改成默认值。"""
        num = _plugin_module._cfg_number
        cfg = _Cfg({"activity.nudge_hour": 0, "activity.min_segment_seconds": 0})
        assert num(cfg, "activity.nudge_hour", 18, int) == 0
        assert num(cfg, "activity.min_segment_seconds", 5.0) == 0.0
        # 取不到 → 默认；值非法 → 默认
        assert num(cfg, "activity.away_seconds", 300.0) == 300.0
        cfg.values["activity.away_seconds"] = "abc"
        assert num(cfg, "activity.away_seconds", 300.0) == 300.0
        cfg.values["activity.away_seconds"] = None
        assert num(cfg, "activity.away_seconds", 300.0) == 300.0

    def test_cached_advice_roundtrip(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        assert p.cached_advice(1) == ""
        p._store.save_advice("day", p._data_signature(1), "多休息")
        assert p.cached_advice(1) == "多休息"
        assert p.advice_is_stale(1) is False

    def test_advice_is_stale_after_new_data(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        start = day_start(time.time())          # 用自然日内的时刻，避免跨午夜抖动
        p._store.add_segment("a.exe", "工作", start, start + 60)
        p._store.save_advice("day", p._data_signature(1), "旧建议")
        assert p.advice_is_stale(1) is False
        p._store.add_segment("b.exe", "工作", start + 60, start + 120)
        assert p.advice_is_stale(1) is True

    def test_clear_data_also_clears_advice(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        start = day_start(time.time())
        p._store.add_segment("a.exe", "工作", start, start + 60)
        p._store.save_advice("day", "x", "建议")
        assert p.clear_data() == 1
        assert p.cached_advice(1) == ""

    def test_nudge_fires_once_a_day(self, monkeypatch):
        p, _ = _quiet_plugin(
            monkeypatch,
            {"activity.enabled": True, "activity.nudge_hour": 0,
             "activity.nudge_enabled": True},
        )
        p.on_ui_ready(p.app)
        start = day_start(time.time())
        p._store.add_segment("a.exe", "工作", start, start + 60)

        p._maybe_nudge()
        first = p._last_nudged_at
        assert first is not None, "满足条件时应当提醒"
        assert p._store.get_meta("last_nudged_at") is not None

        p._maybe_nudge()
        assert p._last_nudged_at == first, "同一天不该重复提醒"

    def test_nudge_blocked_by_fullscreen(self, monkeypatch):
        p, _ = _quiet_plugin(
            monkeypatch,
            {"activity.enabled": True, "activity.nudge_hour": 0},
        )
        p.on_ui_ready(p.app)
        start = day_start(time.time())
        p._store.add_segment("a.exe", "工作", start, start + 60)
        monkeypatch.setattr(p, "_is_fullscreen", lambda: True)
        p._maybe_nudge()
        assert p._last_nudged_at is None
        assert p._store.get_meta("last_nudged_at") is None

    def test_nudge_blocked_when_no_data_today(self, monkeypatch):
        p, _ = _quiet_plugin(
            monkeypatch, {"activity.enabled": True, "activity.nudge_hour": 0}
        )
        p.on_ui_ready(p.app)
        p._maybe_nudge()
        assert p._last_nudged_at is None

    def test_tick_is_safe_without_tracker(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {})
        p.on_ui_ready(p.app)
        p._on_tick()          # 没有 tracker 也不该抛

    def test_start_focus_without_timer(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        assert p.start_focus(25) is False      # 番茄钟插件没加载

    def test_start_focus_uses_shared_timer(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)

        class _Timer:
            def __init__(self):
                self.started = []
                self._running = False

            def is_running(self):
                return self._running

            def start(self, kind="work", minutes=0):
                self.started.append((kind, minutes))
                self._running = True
                return True

        p.app.timer = _Timer()
        assert p.start_focus(25) is True
        assert p.app.timer.started == [("work", 25)]
        assert p.start_focus(25) is False      # 已在运行，不重复起

    def test_start_focus_passes_the_requested_minutes(self, monkeypatch):
        """分钟数必须**真的传下去**，不能被计时器的默认时长吃掉。

        建议卡上写着「开始 45 分钟专注」，点下去就得是 45 分钟。
        P2.18 之前这里 `start("work")` 丢掉了参数，实际跑 25 分钟 ——
        界面说的和做的不一致，而且日志里看不出来。
        """
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)

        class _Timer:
            def __init__(self):
                self.started = []
                self._running = False

            def is_running(self):
                return self._running

            def start(self, kind="work", minutes=0):
                self.started.append((kind, minutes))
                self._running = True
                return True

        p.app.timer = _Timer()
        p.start_focus(45)
        p.app.timer._running = False
        p.start_focus(90)
        assert p.app.timer.started == [("work", 45), ("work", 90)]

    def test_start_focus_reports_running_state(self, monkeypatch):
        """`focus_running()` 是页面与常驻指示判断「要不要画专注态」的唯一入口。"""
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        assert p.focus_running() is False       # 番茄钟插件没加载

        class _Timer:
            def __init__(self):
                self._state = "idle"

            def is_running(self):
                return self._state == "running"

            def is_paused(self):
                return self._state == "paused"

        p.app.timer = _Timer()
        assert p.focus_running() is False
        for state in ("running", "paused"):
            p.app.timer._state = state
            assert p.focus_running() is True


# ---------------------------------------------------------------- 控制中心页


class _PM:
    def __init__(self, plugin=None):
        self._plugin = plugin

    def get_plugin(self, name):
        return self._plugin if name == "activity_advisor" else None

    def get_all_plugins(self):
        return {}


def _page(app):
    from presentation.control_center import ControlCenter, reset_instance

    reset_instance()
    cc = ControlCenter(app=app)
    return next(p for p in cc._pages if p.title == "今日")


def _seed_today(plugin, segments) -> None:
    """往插件的库里塞几段**今天**的记录（时间轴 / 概览靠它出数）。"""
    day = day_start(time.time())
    for offset_min, minutes, app_name, cat in segments:
        start = day + offset_min * 60
        plugin._store.add_segment(app_name, cat, start, start + minutes * 60)


class TestTodayPage:
    """今日页（P2.14）—— 概览 / 时间轴 / 排行 / 建议卡。

    这一组守的是「页面拿到的数据是**真的**」：概览数字来自分段而不是写死、
    时间轴拿到的是**合并后**的分段、忽略要真的落库。
    """

    def test_page_is_registered_as_first_page(self):
        from presentation.control_center import NAV_ITEMS

        assert "今日" in [label for _, label, _ in NAV_ITEMS]
        # 主功能不能藏在设置后面 —— 必须是第一项
        assert NAV_ITEMS[0][1] == "今日"

    def test_degrades_without_plugin(self):
        page = _page(types.SimpleNamespace(plugin_manager=_PM(None)))
        assert page._chk_enabled.isEnabled() is False
        assert page._btn_analyze.isEnabled() is False
        assert page._btn_focus.isEnabled() is False
        assert page._btn_clear.isEnabled() is False
        assert "插件未加载" in page._empty.title()
        assert page._empty.isHidden() is False

    def test_shows_empty_state_when_collection_disabled(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": False})
        p.on_ui_ready(p.app)
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))
        assert page._empty.isHidden() is False
        assert "采集已关闭" in page._empty.title()
        assert page._dashboard.isHidden() is True

    def test_toggle_drives_plugin(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": False})
        p.on_ui_ready(p.app)
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))

        assert page._chk_enabled.isChecked() is False
        page._chk_enabled.setChecked(True)          # 用户点开关
        assert p.is_enabled() is True
        assert page.selected_days() == 1            # 固定「今天」

    def test_default_range_is_today(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))
        assert page.selected_days() == 1

    def test_view_protocol_matches_plugin(self, monkeypatch):
        """页面与插件之间靠鸭子类型广播 —— 少一个方法就少一处更新。

        `set_overview` **不在**协议里：今日页自己拉分段画图，
        不再接收一段纯文本概览（那是插件对话框的旧协议）。
        """
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))
        for method in ("set_status", "set_advice", "append_advice", "set_analyzing"):
            assert callable(getattr(page, method)), method
        assert not hasattr(page, "set_overview"), "今日页不该再接收纯文本概览"
        p._broadcast("append_advice", "增量")
        page.set_analyzing(False)
        assert "增量" in page._raw.toPlainText()

    def test_focus_button_reports_when_timer_missing(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))
        page._on_focus()
        assert "番茄钟" in page._status.text()

    # ----- 数据真的上屏 -----

    def test_overview_tiles_use_real_segments(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_today(p, [
            (9 * 60, 60, "code.exe", "工作"),
            (10 * 60, 30, "chrome.exe", "浏览"),
        ])
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))

        assert page._dashboard.isHidden() is False
        assert page._tiles["total"].value() == human_duration(90 * 60)
        assert page._tiles["focus"].value() == human_duration(60 * 60)
        assert page._tiles["top"].value() == "code.exe"
        assert page._tiles["switch"].value() == "1 次"

    # ----- 概览必须是一块「仪表盘」，不是几个散落的灰块（P2.15）-----

    def test_overview_is_wrapped_in_exactly_one_board(self, monkeypatch):
        """四个指标格必须收进**同一块** OverviewBoard。

        改之前它们是四个 `surface_alt` 灰块直接摊在页面底色上 ——
        浅色主题下 `surface_alt`(#F7F7F7) 与 `window`(#F3F3F3) 只差 4 级，
        看上去跟「什么都没有」一样。整页最该被看见的信息反而最不显眼。
        """
        from PySide6.QtWidgets import QFrame

        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_today(p, [(9 * 60, 60, "code.exe", "工作")])
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))

        boards = page.findChildren(QFrame, "overviewBoard")
        assert len(boards) == 1, "概览应当且只应当有一块台面"
        board = boards[0]
        assert board.title() == "今日概览"
        for key, tile in page._tiles.items():
            assert board.tile(key) is tile, f"{key} 没在台面上"

    def test_headline_tile_is_stretched_wider(self, monkeypatch):
        """页面必须给头条那格**更大的伸展因子**。

        「更明显」不只靠颜色：四格等宽的话，扫过去仍是一排并列的方块，
        主次出不来。

        为什么不直接量宽度：页面在测试里不会真正 show（它是 QStackedWidget
        里的一页），布局不跑，`width()` 全是 Qt 的默认值 640 —— 量出来四格
        一样宽，断言要么永真要么误报。所以这里只断言「页面给对了伸展因子」，
        「伸展因子真的会变宽」由 `tests/test_design.py` 的像素用例守。
        """
        from PySide6.QtWidgets import QFrame

        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_today(p, [(9 * 60, 60, "code.exe", "工作")])
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))

        board = page.findChildren(QFrame, "overviewBoard")[0]
        rest = max(board.stretch_of(k) for k in ("focus", "top", "switch"))
        assert board.stretch_of("total") > rest, (
            f"头条格没拿到更大的伸展因子："
            f"{ {k: board.stretch_of(k) for k in page._tiles} }"
        )

    def test_only_the_headline_number_is_primary(self, monkeypatch):
        """四格只有一格是 primary，而且必须是「今日总时长」。

        四个指标不是同等重要：总时长是这一页的头条数字，其余三个是它的
        分解。全部一样大等于没有重点 —— 这条把「谁是头条」钉死。
        """
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_today(p, [(9 * 60, 60, "code.exe", "工作")])
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))

        primaries = [k for k, t in page._tiles.items() if t.is_primary()]
        assert primaries == ["total"], primaries

    def test_timeline_gets_merged_segments(self, monkeypatch):
        """时间轴必须拿到**合并后**的分段 —— 否则一天几十根细线看不清。"""
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        # 同应用、间隔 0 分钟的三段 → 合并成一段
        _seed_today(p, [
            (9 * 60, 20, "code.exe", "工作"),
            (9 * 60 + 20, 20, "code.exe", "工作"),
            (9 * 60 + 40, 20, "code.exe", "工作"),
        ])
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))
        assert page._timeline.segment_count() == 1

    def test_rank_bar_lists_top_apps(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_today(p, [
            (9 * 60, 60, "code.exe", "工作"),
            (10 * 60, 30, "chrome.exe", "浏览"),
        ])
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))
        assert page._rank.row_count() == 2

    def test_timeline_axis_has_ticks(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_today(p, [(9 * 60, 60, "code.exe", "工作")])
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))
        assert page._axis.count() == 5
        assert page._axis.text_at(0) == "0:00"

    # ----- 建议卡 -----

    def test_structured_advice_renders_cards(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_today(p, [(9 * 60, 60, "code.exe", "工作")])
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))

        page.set_advice(_GOOD_JSON)
        page.set_analyzing(False)
        assert page._cards[0].isHidden() is False
        assert "上午的深度工作被切成 4 段" in page._cards[0].headline()
        assert page._cards[1].isHidden() is False
        assert page._cards[2].isHidden() is True       # 只有两条
        assert page._raw.isHidden() is True            # 结构化时走卡片，不走纯文本

    def test_plain_text_advice_falls_back_to_raw(self, monkeypatch):
        """模型没按 JSON 回答时**原样显示**，不硬塞进卡片壳里。"""
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_today(p, [(9 * 60, 60, "code.exe", "工作")])
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))

        page.set_advice("今天上午被打断得比较多，建议把通知关掉试试。")
        page.set_analyzing(False)
        assert "建议把通知关掉" in page._raw.toPlainText()
        assert page._raw.isHidden() is False
        assert all(c.isHidden() for c in page._cards)

    def test_streaming_does_not_flash_half_json(self, monkeypatch):
        """流式过程中不渲染 —— 半截 JSON 逐块画会闪一堆残缺卡片。"""
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_today(p, [(9 * 60, 60, "code.exe", "工作")])
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))

        page.set_analyzing(True)
        page.append_advice('[{"headline": "上午的深')
        assert all(c.isHidden() for c in page._cards)
        assert page._raw.isHidden() is True

    def test_ignored_advice_disappears_and_persists(self, monkeypatch):
        """点「忽略」后：卡片消失，且**落库**（换个视图也不会再冒出来）。"""
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_today(p, [(9 * 60, 60, "code.exe", "工作")])
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))
        page.set_advice(_GOOD_JSON)
        page.set_analyzing(False)

        fp = page._cards[0].advice().fingerprint
        page._on_card_decided(page._cards[0].advice(), ACTION_IGNORE)

        assert fp in p.ignored_fingerprints()
        assert "上午的深度工作被切成 4 段" not in page._cards[0].headline()
        # 插件层的过滤也生效（对话框那条路径同样看不到）
        assert all(a.fingerprint != fp for a in p.structured_advice(1))
        # 留痕与过滤是两件事：忽略既要挡住这条建议，也要留下决定依据
        notes = p.decision_log()
        assert len(notes) == 1 and notes[0].action == ACTION_IGNORE
        assert notes[0].fingerprint == fp

    def test_card_action_starts_focus(self, monkeypatch):
        """卡片上的动作要真的驱动番茄钟，而不只是改个状态文字。"""
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_today(p, [(9 * 60, 60, "code.exe", "工作")])
        started = []
        monkeypatch.setattr(p, "start_focus",
                            lambda minutes=25: started.append(minutes) or True)
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))
        page.set_advice(_GOOD_JSON)
        page._on_card_decided(page._cards[0].advice(), ACTION_ADOPT)
        assert started == [45], "按钮写着 45 分钟，就必须跑 45 分钟"

    def test_adopt_records_what_actually_happened(self, monkeypatch):
        """采纳的留痕要记**实际结果**：计时已经在跑时不能写成「已开始」。"""
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_today(p, [(9 * 60, 60, "code.exe", "工作")])
        monkeypatch.setattr(p, "start_focus", lambda minutes=25: False)
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))
        page.set_advice(_GOOD_JSON)
        page._on_card_decided(page._cards[0].advice(), ACTION_ADOPT)

        notes = p.decision_log()
        assert len(notes) == 1 and notes[0].action == ACTION_ADOPT
        assert "未开始专注" in notes[0].impact
        assert "已开始" not in notes[0].impact

    def test_clear_asks_for_confirmation(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_today(p, [(9 * 60, 60, "code.exe", "工作")])
        page = _page(types.SimpleNamespace(plugin_manager=_PM(p)))
        page.center.confirm = lambda *a, **k: False        # 用户点了「否」
        page._on_clear()
        assert p._store.count() == 1, "没确认就删了数据"


# ---------------------------------------------------------------- 结构化建议（P2.14）

_GOOD_JSON = (
    '[{"headline": "上午的深度工作被切成 4 段",'
    ' "evidence": ["微信在 08:00-12:00 打断 9 次", "VS Code 最长连续 1h30m"],'
    ' "action": {"kind": "focus", "minutes": 45}},'
    ' {"headline": "下午节奏变碎", "evidence": ["切换了 11 次窗口"],'
    ' "action": {"kind": "none"}}]'
)


class TestAdviceParse:
    def test_parses_clean_json(self):
        items = parse_advices(_GOOD_JSON)
        assert len(items) == 2
        assert items[0].headline == "上午的深度工作被切成 4 段"
        assert len(items[0].evidence) == 2
        assert items[0].action.kind == ACTION_FOCUS
        assert items[0].action.minutes == 45
        assert items[0].action.is_actionable is True

    def test_parses_fenced_json(self):
        """模型爱包 ```json 代码块 —— 去围栏后要能解析。"""
        items = parse_advices("```json\n" + _GOOD_JSON + "\n```")
        assert len(items) == 2

    def test_parses_json_with_prose_prefix(self):
        """模型爱在前面加一句「好的，这是建议：」—— 抠出数组即可。"""
        items = parse_advices("好的，这是建议：\n" + _GOOD_JSON + "\n希望有帮助。")
        assert len(items) == 2

    def test_parses_single_object(self):
        items = parse_advices('{"headline": "只有一条", "evidence": ["x"]}')
        assert len(items) == 1 and items[0].headline == "只有一条"

    def test_parses_dict_with_advices_key(self):
        text = '{"advices": [{"headline": "A", "action": {"kind": "none"}}]}'
        items = parse_advices(text)
        assert len(items) == 1 and items[0].headline == "A"

    def test_action_kind_is_restricted(self):
        """模型发明的动作类型必须被拒 —— 否则 UI 无法执行。

        注意这里**必须带上合法的 minutes**：只给非法 kind 的话，
        「没有动作」也可能是因为缺时长，测不出类型检查本身是否生效。
        """
        text = ('[{"headline": "A",'
                ' "action": {"kind": "open_settings_page", "minutes": 45}}]')
        items = parse_advices(text)
        assert items[0].action.kind == ACTION_NONE
        assert items[0].action.is_actionable is False

    def test_minutes_clamped_to_allowed(self):
        """60 分钟不在允许集合里，夹到最近的 45。"""
        text = '[{"headline": "A", "action": {"kind": "focus", "minutes": 60}}]'
        assert parse_advices(text)[0].action.minutes == 45
        text2 = '[{"headline": "A", "action": {"kind": "focus", "minutes": 30}}]'
        assert parse_advices(text2)[0].action.minutes == 25

    def test_nonpositive_minutes_gives_no_action(self):
        for raw in ("0", "-5", '"abc"', "null"):
            text = ('[{"headline": "A", "action": {"kind": "focus", "minutes": '
                    + raw + "}}]")
            adv = parse_advices(text)[0]
            assert adv.action.is_actionable is False, raw

    def test_missing_action_gives_no_action(self):
        items = parse_advices('[{"headline": "A"}]')
        assert items[0].action.kind == ACTION_NONE
        assert items[0].action.is_actionable is False

    def test_evidence_capped(self):
        ev = ", ".join(f'"e{i}"' for i in range(6))
        items = parse_advices('[{"headline": "A", "evidence": [' + ev + "]}]")
        assert len(items[0].evidence) == MAX_EVIDENCE

    def test_evidence_accepts_plain_string(self):
        items = parse_advices('[{"headline": "A", "evidence": "只有一条证据"}]')
        assert items[0].evidence == ("只有一条证据",)

    def test_advices_capped(self):
        body = ", ".join(f'{{"headline": "H{i}"}}' for i in range(9))
        items = parse_advices("[" + body + "]")
        assert len(items) == MAX_ADVICES

    def test_skips_entries_without_headline(self):
        items = parse_advices('[{"headline": ""}, {"headline": "有效"}]')
        assert len(items) == 1 and items[0].headline == "有效"

    def test_fallback_on_garbage(self):
        """完全不是 JSON 也不能白屏 —— 降级成一条没有证据的建议。"""
        items = parse_advices("今天状态不错，建议多休息。\n第二条随便写的。")
        assert len(items) == 1
        assert items[0].headline.startswith("今天状态不错")
        assert items[0].action.is_actionable is False
        assert len(items[0].evidence) >= 1

    def test_empty_input_returns_empty(self):
        assert parse_advices("") == []
        assert parse_advices("   \n  ") == []

    def test_fingerprint_ignores_numbers_and_punctuation(self):
        """数字和标点不同、语义相同 → 同一个指纹（忽略才拦得住）。"""
        assert advice_fingerprint("上午被打断 9 次。") == advice_fingerprint("上午被打断 8 次！")

    def test_fingerprint_distinguishes_different_topics(self):
        """时段不同就是不同的建议，不能被合并。"""
        assert advice_fingerprint("上午被打断 9 次") != advice_fingerprint("下午被打断 9 次")

    def test_advice_to_text_round_trip(self):
        text = advice_to_text(parse_advices(_GOOD_JSON))
        assert "上午的深度工作被切成 4 段" in text
        assert "开始 45 分钟专注" in text
        assert "VS Code 最长连续 1h30m" in text


class TestAdvisorJsonContract:
    """提示词必须把 JSON 格式说清楚 —— 否则解析器天天走降级分支。"""

    def test_system_prompt_carries_json_spec(self):
        for key in ("headline", "evidence", "action", "focus", "none"):
            assert key in ADVISOR_SYSTEM_PROMPT, key

    def test_question_prompt_carries_json_spec(self):
        prompt = build_advisor_prompt("统计区间：xxx", days=1)
        assert "headline" in prompt
        assert ADVICE_JSON_SPEC in prompt

    def test_system_prompt_forbids_fabricated_evidence(self):
        """证据必须来自真实数据 —— 这条约束没了，建议卡就变成新的幻觉来源。"""
        assert "真实出现过" in ADVISOR_SYSTEM_PROMPT


# ---------------------------------------------------------------- 段合并 / 聚合（P2.14）


class TestTimelineMerge:
    def test_merges_same_app_within_gap(self):
        """切走 30 秒又切回来 —— 该算一段，否则时间轴全是细线。"""
        segs = [_seg("code.exe", "工作", 0, 600), _seg("code.exe", "工作", 630, 1200)]
        merged = merge_segments(segs)
        assert len(merged) == 1
        assert merged[0]["seconds"] == pytest.approx(1200.0)

    def test_does_not_merge_beyond_gap(self):
        segs = [_seg("code.exe", "工作", 0, 600), _seg("code.exe", "工作", 900, 1500)]
        assert len(merge_segments(segs, gap_seconds=120)) == 2

    def test_does_not_merge_different_apps(self):
        """不同应用合并了就等于把「在聊天」画成「在写代码」—— 骗人。"""
        segs = [_seg("code.exe", "工作", 0, 600), _seg("wechat.exe", "沟通", 610, 1200)]
        assert len(merge_segments(segs)) == 2

    def test_can_merge_across_apps_when_disabled(self):
        segs = [_seg("code.exe", "工作", 0, 600), _seg("wechat.exe", "沟通", 610, 1200)]
        merged = merge_segments(segs, same_app_only=False)
        assert len(merged) == 1
        assert merged[0]["app"] == "code.exe"      # 保留先出现的那段的应用

    def test_does_not_mutate_input(self):
        segs = [_seg("code.exe", "工作", 0, 600), _seg("code.exe", "工作", 630, 1200)]
        merge_segments(segs)
        assert segs[0]["end_at"] == 600.0 and segs[0]["seconds"] == 600.0

    def test_sorts_by_start_time(self):
        segs = [_seg("code.exe", "工作", 630, 1200), _seg("code.exe", "工作", 0, 600)]
        merged = merge_segments(segs)
        assert len(merged) == 1 and merged[0]["start_at"] == 0.0

    def test_key_rate_takes_max(self):
        segs = [_seg("code.exe", "工作", 0, 600, rate=3), _seg("code.exe", "工作", 630, 1200, rate=9)]
        assert merge_segments(segs)[0]["key_rate"] == 9

    def test_empty_input(self):
        assert merge_segments([]) == []


class TestTimelineAggregates:
    def test_total_and_focus_seconds(self):
        segs = [
            _seg("code.exe", WORK_CATEGORY, 0, 3600),
            _seg("wechat.exe", "沟通", 3600, 4200),
        ]
        assert total_seconds(segs) == pytest.approx(4200.0)
        assert focus_seconds(segs) == pytest.approx(3600.0)

    def test_focus_excludes_non_work(self):
        segs = [_seg("game.exe", "娱乐", 0, 3600)]
        assert focus_seconds(segs) == 0.0

    def test_switch_count(self):
        segs = [
            _seg("a.exe", "工作", 0, 60),
            _seg("a.exe", "工作", 60, 120),   # 同应用，不算切换
            _seg("b.exe", "沟通", 120, 180),  # 切换
            _seg("a.exe", "工作", 180, 240),  # 切换
        ]
        assert switch_count(segs) == 2

    def test_switch_count_ignores_cross_day_boundary(self):
        """隔夜不是「切换应用」。

        「昨天收工在浏览器、今天开工写代码」不该算一次切换。算进去有两个
        后果，都不会报错：① 多日数据里每天凭空多一次；② 那次会被归到
        **当天开工的那个小时** —— 趋势页于是说「早上 9 点最容易被打断」，
        而用户 9 点只是刚打开电脑（P2.14 目检发现）。
        """
        day = day_start(time.time())
        segs = [
            _seg("chrome.exe", "浏览", day - DAY_SECONDS + 16 * 3600,
                 day - DAY_SECONDS + 17 * 3600),
            _seg("code.exe", "工作", day + 9 * 3600, day + 11 * 3600),
        ]
        assert switch_count(segs) == 0
        assert hour_switches(segs) == [0] * HOURS_PER_DAY

    def test_switch_count_is_order_independent_with_cross_day_data(self):
        """乱序输入也不能数错。

        有了「同一天才算」的判据之后必须**先排序**再判：否则「前一段」
        可能根本不是时间上的前一段，同一天的两次真实切换会被误判成
        跨天而整个漏掉。
        """
        day = day_start(time.time())
        a = _seg("a.exe", "工作", day + 9 * 3600, day + 10 * 3600)
        y = _seg("y.exe", "工作", day - DAY_SECONDS + 9 * 3600,
                 day - DAY_SECONDS + 10 * 3600)
        b = _seg("b.exe", "沟通", day + 10 * 3600, day + 10 * 3600 + 300)
        assert switch_count([a, y, b]) == 1
        assert switch_count([a, b, y]) == 1
        assert switch_count([y, b, a]) == 1

    def test_top_apps_limit_and_order(self):
        segs = [
            _seg("a.exe", "工作", 0, 3600),
            _seg("b.exe", "沟通", 0, 1800),
            _seg("c.exe", "娱乐", 0, 600),
        ]
        top = top_apps(segs, limit=2)
        assert [t["app"] for t in top] == ["a.exe", "b.exe"]
        assert top[0]["seconds"] == pytest.approx(3600.0)

    def test_category_totals_descending(self):
        segs = [
            _seg("a.exe", "工作", 0, 600),
            _seg("b.exe", "沟通", 0, 1800),
        ]
        rows = category_totals(segs)
        assert rows[0]["category"] == "沟通"
        assert rows[1]["category"] == "工作"


class TestDailyTotals:
    def test_returns_ascending_days(self):
        now = _local_ts(2026, 10, 13, 20)
        rows = daily_totals([], days=7, now=now)
        assert len(rows) == 7
        starts = [r["start"] for r in rows]
        assert starts == sorted(starts)
        assert rows[-1]["day"] == "10-13"

    def test_includes_empty_days(self):
        """空日必须占位 —— 缺一天会让柱状图看起来像连续两天在工作。"""
        now = _local_ts(2026, 10, 13, 20)
        rows = daily_totals([], days=3, now=now)
        assert [r["total"] for r in rows] == [0.0, 0.0, 0.0]

    def test_attributes_cross_midnight_to_start_day(self):
        """跨天段归到**开始**那天，否则同一段会被两天各算一次。"""
        now = _local_ts(2026, 10, 13, 20)
        night = _seg("code.exe", WORK_CATEGORY,
                     _local_ts(2026, 10, 12, 23), _local_ts(2026, 10, 13, 1))
        rows = {r["day"]: r for r in daily_totals([night], days=3, now=now)}
        assert rows["10-12"]["total"] == pytest.approx(7200.0)
        assert rows["10-13"]["total"] == 0.0

    def test_splits_total_and_focus(self):
        now = _local_ts(2026, 10, 13, 20)
        segs = [
            _seg("code.exe", WORK_CATEGORY, _local_ts(2026, 10, 13, 9), _local_ts(2026, 10, 13, 10)),
            _seg("wechat.exe", "沟通", _local_ts(2026, 10, 13, 10), _local_ts(2026, 10, 13, 10, 30)),
        ]
        rows = {r["day"]: r for r in daily_totals(segs, days=1, now=now)}
        assert rows["10-13"]["total"] == pytest.approx(5400.0)
        assert rows["10-13"]["focus"] == pytest.approx(3600.0)

    def test_days_at_least_one(self):
        assert len(daily_totals([], days=0, now=_local_ts(2026, 10, 13, 20))) == 1


# ---------------------------------------------------------------- 已忽略的建议（P2.14）


class TestIgnoredAdvice:
    def test_ignore_and_list(self, store):
        assert store.ignored_fingerprints() == set()
        store.ignore_advice("abc123", "某条建议")
        assert "abc123" in store.ignored_fingerprints()
        assert store.count_ignored() == 1

    def test_ignore_is_idempotent(self, store):
        store.ignore_advice("abc", "一")
        store.ignore_advice("abc", "二")
        assert store.count_ignored() == 1

    def test_clear_also_clears_ignored(self, store):
        """清空行为数据必须连忽略标记一起清 ——
        否则用户清空后新生成的建议仍被旧标记挡掉，还找不到原因。"""
        store.add_segment("code.exe", "工作", 0, 600)
        store.ignore_advice("abc", "一")
        store.clear()
        assert store.count_ignored() == 0
        assert store.ignored_fingerprints() == set()

    def test_clear_ignored_alone(self, store):
        store.ignore_advice("abc", "一")
        assert store.clear_ignored() == 1
        assert store.count_ignored() == 0

    def test_fingerprint_round_trip_with_advice(self, store):
        """Advice.fingerprint 与 store 的键能对上。"""
        adv = Advice(headline="上午被打断 9 次")
        store.ignore_advice(adv.fingerprint, adv.headline)
        assert adv.fingerprint in store.ignored_fingerprints()


# ---------------------------------------------------------------- 打断时段（P2.14 趋势）


class TestHourSwitches:
    """按小时的打断分布 —— 趋势页「最容易被打断的时段」的数据源。

    这一组守两件容易「静默出错」的事：
    ① 切换归到**后一段**的小时（归错方向只会整体早一小时，看着很合理）；
    ② 输入先排序（不排序会把同一对应用数很多次）。
    两种错都不会抛异常，只会让页面给出一句错误的结论。
    """

    def test_buckets_cover_every_hour(self):
        assert len(hour_switches([])) == HOURS_PER_DAY == 24
        assert hour_switches([]) == [0] * HOURS_PER_DAY

    def test_same_app_is_not_a_switch(self):
        day = day_start(time.time())
        segs = [
            _seg("code.exe", "工作", day + 9 * 3600, day + 9 * 3600 + 600),
            _seg("code.exe", "工作", day + 9 * 3600 + 600, day + 9 * 3600 + 1200),
        ]
        assert hour_switches(segs) == [0] * HOURS_PER_DAY
        assert busiest_hour(segs) is None

    def test_switch_goes_to_the_later_hour(self):
        """切换发生在「切到新应用」的那一刻 —— 归到后一段的小时。

        归错方向不会报错，只会让「最容易被打断的时段」整体早一个小时，
        而用户对照自己的日程时是发现不了的（差一小时看起来也很合理）。
        """
        day = day_start(time.time())
        a = _seg("code.exe", "工作", day + 9 * 3600 + 59 * 60, day + 10 * 3600)
        b = _seg("wechat.exe", "沟通", day + 10 * 3600, day + 10 * 3600 + 300)
        buckets = hour_switches([a, b])
        assert buckets[10] == 1
        assert buckets[9] == 0

    def test_sorts_before_counting(self):
        """顺序错了会把同一对应用数很多次 —— 必须自己排序，不信调用方给的顺序。"""
        day = day_start(time.time())
        a = _seg("code.exe", "工作", day + 9 * 3600, day + 10 * 3600)
        b = _seg("wechat.exe", "沟通", day + 10 * 3600, day + 10 * 3600 + 300)
        assert hour_switches([b, a]) == hour_switches([a, b])
        assert hour_switches([b, a])[10] == 1

    def test_busiest_hour_finds_the_peak(self):
        day = day_start(time.time())
        segs = [
            _seg("a.exe", "工作", day + 9 * 3600, day + 9 * 3600 + 600),
            _seg("b.exe", "沟通", day + 9 * 3600 + 600, day + 9 * 3600 + 900),
        ]
        for k in range(3):                      # 15 点连着切三次
            base = day + 15 * 3600 + k * 600
            segs.append(_seg(f"c{k}.exe", "工作", base, base + 300))
            segs.append(_seg(f"d{k}.exe", "沟通", base + 300, base + 600))
        buckets = hour_switches(segs)
        assert buckets[15] > buckets[9] > 0
        assert busiest_hour(segs) == 15

    def test_busiest_hour_is_none_when_nothing_switched(self):
        """`None` 而不是 `0` —— 0 点是合法答案，见下一条。"""
        assert busiest_hour([]) is None
        assert busiest_hour([_seg("code.exe", "工作", 0, 3600)]) is None

    def test_midnight_switch_returns_zero_not_none(self):
        """0 点是**合法答案**（熬夜干活）—— 反过来说明 None 只表示「没有切换」。"""
        day = day_start(time.time())
        segs = [
            _seg("a.exe", "工作", day, day + 60),
            _seg("b.exe", "沟通", day + 60, day + 120),
        ]
        assert busiest_hour(segs) == 0

    def test_hour_of_day_and_label(self):
        day = day_start(time.time())
        assert hour_of_day(day + 7 * 3600 + 1800) == 7
        assert hour_label(7) == "07:00–08:00"

    def test_hour_label_never_wraps_to_00(self):
        """23 点的右端写 `24:00` —— 「23:00–00:00」会被读成倒着走。"""
        assert hour_label(23) == "23:00–24:00"
        assert hour_label(99) == "23:00–24:00"      # 越界夹住
        assert hour_label(-1) == "00:00–01:00"


# ---------------------------------------------------------------- 周期对比（P2.14 趋势）


class TestPeriodCompare:
    """本周期 vs 紧邻的上一个同长周期。"""

    def test_bounds_are_contiguous(self):
        now = _local_ts(2026, 10, 13, 20)
        cur_start, cur_end, prev_start, prev_end = period_bounds(7, now)
        assert prev_end == cur_start, "两段必须紧邻、不留缝也不重叠"
        assert cur_end == pytest.approx(float(now))
        assert cur_start - prev_start == pytest.approx(7 * DAY_SECONDS)

    def test_bounds_use_natural_days_not_rolling_window(self):
        """口径必须与 `since_for_days` 一致（自然日）。

        滚动窗口（`now - n*86400`）会把「上周同一天的下午」算进本周期，
        于是同一个下午会被两个周期各算一次。
        """
        now = _local_ts(2026, 10, 13, 20)
        cur_start, _, _, _ = period_bounds(7, now)
        assert cur_start == day_start(now) - 6 * DAY_SECONDS
        assert cur_start == since_for_days(7, now)

    def test_days_at_least_one(self):
        now = _local_ts(2026, 10, 13, 20)
        cur_start, _, prev_start, _ = period_bounds(0, now)
        assert cur_start == day_start(now)
        assert prev_start == day_start(now) - DAY_SECONDS

    def test_splits_segments_between_periods(self):
        now = _local_ts(2026, 10, 13, 20)
        segs = [
            _seg("code.exe", WORK_CATEGORY,
                 _local_ts(2026, 10, 13, 9), _local_ts(2026, 10, 13, 10)),
            _seg("code.exe", WORK_CATEGORY,
                 _local_ts(2026, 10, 3, 9), _local_ts(2026, 10, 3, 9, 30)),
        ]
        got = compare_periods(segs, days=7, now=now)
        assert got["current"]["total"] == pytest.approx(3600.0)
        assert got["current"]["count"] == 1
        assert got["previous"]["total"] == pytest.approx(1800.0)
        assert got["previous"]["count"] == 1
        assert got["delta_seconds"] == pytest.approx(1800.0)
        assert got["delta_ratio"] == pytest.approx(1.0)

    def test_hands_out_only_this_periods_segments(self):
        """`current["segments"]` 必须是**本周期**那一段的列表。

        趋势页要用它算「时间构成 / 按小时打断」—— 页面拿到的是
        `days * 2` 天的混合列表，切分口径只能在这里（见 `compare_periods`
        docstring：混着算会让同一页上「本周期总时长」和「时间构成」
        分别是 7 天和 14 天的量）。
        """
        now = _local_ts(2026, 10, 13, 20)
        a = _seg("code.exe", WORK_CATEGORY,
                 _local_ts(2026, 10, 13, 9), _local_ts(2026, 10, 13, 10))
        b = _seg("chrome.exe", "浏览",
                 _local_ts(2026, 10, 3, 9), _local_ts(2026, 10, 3, 10))
        got = compare_periods([a, b], days=7, now=now)
        assert got["current"]["segments"] == [a]
        assert got["previous"]["segments"] == [b]

    def test_delta_ratio_is_none_when_previous_is_empty(self):
        """上周期为 0 时**不能**算比例 —— 会除零，或者显示「增长 0%」这种假话。"""
        now = _local_ts(2026, 10, 13, 20)
        segs = [_seg("code.exe", WORK_CATEGORY,
                     _local_ts(2026, 10, 13, 9), _local_ts(2026, 10, 13, 10))]
        got = compare_periods(segs, days=7, now=now)
        assert got["previous"]["total"] == 0.0
        assert got["delta_ratio"] is None
        assert got["delta_seconds"] == pytest.approx(3600.0)

    def test_boundary_belongs_to_current(self):
        """正好落在 `cur_start` 的段属于**本周期**（边界左闭右开）。"""
        now = _local_ts(2026, 10, 13, 20)
        cur_start, _, _, _ = period_bounds(7, now)
        segs = [_seg("code.exe", WORK_CATEGORY, cur_start, cur_start + 600)]
        got = compare_periods(segs, days=7, now=now)
        assert got["current"]["count"] == 1
        assert got["previous"]["count"] == 0

    def test_ignores_segments_older_than_both_periods(self):
        now = _local_ts(2026, 10, 13, 20)
        old = _seg("code.exe", WORK_CATEGORY,
                   _local_ts(2026, 9, 1, 9), _local_ts(2026, 9, 1, 12))
        got = compare_periods([old], days=7, now=now)
        assert got["current"]["total"] == 0.0
        assert got["previous"]["total"] == 0.0
        assert got["delta_ratio"] is None

    def test_switch_count_is_per_period(self):
        """切换次数要**各算各的** —— 两段拼一起会多出一次假的跨周期切换。"""
        now = _local_ts(2026, 10, 13, 20)
        segs = [
            _seg("a.exe", WORK_CATEGORY,
                 _local_ts(2026, 10, 13, 9), _local_ts(2026, 10, 13, 10)),
            _seg("b.exe", "沟通",
                 _local_ts(2026, 10, 3, 9), _local_ts(2026, 10, 3, 10)),
        ]
        got = compare_periods(segs, days=7, now=now)
        assert got["current"]["switches"] == 0
        assert got["previous"]["switches"] == 0

    def test_focus_uses_work_category_only(self):
        now = _local_ts(2026, 10, 13, 20)
        segs = [
            _seg("code.exe", WORK_CATEGORY,
                 _local_ts(2026, 10, 13, 9), _local_ts(2026, 10, 13, 10)),
            _seg("game.exe", "娱乐",
                 _local_ts(2026, 10, 13, 10), _local_ts(2026, 10, 13, 11)),
        ]
        got = compare_periods(segs, days=7, now=now)
        assert got["current"]["total"] == pytest.approx(7200.0)
        assert got["current"]["focus"] == pytest.approx(3600.0)


# ---------------------------------------------------------------- 专注反馈 + 总结（P2.18）


class _FocusTimer:
    """一个能背下 `start / pause / resume / stop` 的假番茄钟。"""

    def __init__(self, state="idle", remaining=0, progress=0.0, total=0):
        self.status = {
            "state": state, "remaining": remaining, "progress": progress,
            "type": "work", "formatted": "00:00",
            "total": total, "today_count": 0,
        }
        self.calls = []

    def get_status(self):
        return dict(self.status)

    def is_running(self):
        return self.status["state"] == "running"

    def is_paused(self):
        return self.status["state"] == "paused"

    def start(self, kind="work", minutes=0):
        self.calls.append(("start", kind, minutes))
        self.status.update(state="running", remaining=minutes * 60, progress=0.0)
        return True

    def pause(self):
        self.calls.append(("pause",))
        self.status["state"] = "paused"
        return True

    def resume(self):
        self.calls.append(("resume",))
        self.status["state"] = "running"
        return True

    def stop(self):
        self.calls.append(("stop",))
        self.status.update(state="idle", remaining=0, progress=0.0)
        return True


def _focus_page(monkeypatch, timer=None, enabled=True):
    """建一个「今日」页，并给它一个假的番茄钟（或没有）。

    计时器要挂在**两处**：插件读自己的 `self.app.timer`（真正启动计时），
    页面读自己的 `app.timer`（画卡片）。只挂一处就会出现
    「插件启动了但卡片不动」或者反过来。
    """
    p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": enabled})
    p.on_ui_ready(p.app)
    _seed_today(p, [(9 * 60, 60, "code.exe", "工作")])
    p.app.timer = timer
    page = _page(types.SimpleNamespace(plugin_manager=_PM(p), timer=timer))
    return p, page


_ADVICE_WITH_SUMMARY = (
    '{"summary": "今天深度工作只占 2 小时，下午被切得比较碎",'
    ' "advices": [{"headline": "上午被切成 4 段", "evidence": ["切换 4 次"],'
    '  "action": {"kind": "focus", "minutes": 45}}]}'
)


class TestTodayFocusFeedback:
    """点「专注」必须有**持续可见**的反馈（P2.18）。

    守的是「状态变化真的上了屏」：卡片展开、按钮换字、进度环改口径。
    只改状态不加界面的话，用户看到的就是原来那个「点了没反应」。
    """

    def test_card_appears_while_the_session_runs(self, monkeypatch):
        timer = _FocusTimer("running", 12 * 60 + 34, 0.5)
        _, page = _focus_page(monkeypatch, timer)
        page._focus_card.set_status_provider(page._focus_status)

        assert page._focus_card.is_active() is True
        assert page._focus_card.clock_text() == "12:34"
        assert page._focus_card.bar_value() == 50

    def test_card_stays_collapsed_when_there_is_no_timer(self, monkeypatch):
        _, page = _focus_page(monkeypatch, None)
        page._focus_card.set_status_provider(page._focus_status)
        assert page._focus_card.is_active() is False

    def test_header_button_becomes_a_state_indicator(self, monkeypatch):
        """按钮自己要改口 —— 卡里写着专注中、按钮还写着「开始」是自相矛盾。"""
        _, page = _focus_page(monkeypatch, _FocusTimer("idle"))
        page._on_focus_state("running")
        assert page._btn_focus.isEnabled() is False
        assert page._btn_focus.text() == "专注中…"

        page._on_focus_state("paused")
        assert page._btn_focus.text() == "已暂停"

        page._on_focus_state("idle")
        assert page._btn_focus.isEnabled() is True
        assert page._btn_focus.text().startswith("开始 ")

    def test_button_uses_the_configured_work_duration(self, monkeypatch):
        """按钮写的分钟数要和番茄钟设置一致 —— 写死 25 会变成一句谎话。"""
        _, page = _focus_page(monkeypatch, _FocusTimer("idle"))
        page.app.plugin_manager.get_plugin("activity_advisor")
        from data.config_manager import config_manager

        old = config_manager.get("tomato.work_duration", 25)
        try:
            config_manager.set("tomato.work_duration", 45)
            assert page._focus_button_text("idle") == "开始 45 分钟专注"
        finally:
            config_manager.set("tomato.work_duration", old)

    def test_starting_a_focus_asks_for_the_advice_minutes(self, monkeypatch):
        """建议卡上写着 45 分钟，点下去就得是 45 分钟。"""
        timer = _FocusTimer("idle")
        _, page = _focus_page(monkeypatch, timer)
        page._start_focus(45)
        assert timer.calls == [("start", "work", 45)]

    def test_card_expands_right_after_starting(self, monkeypatch):
        """点完立刻读一次 —— 不能让用户等最多 1 秒才看到卡片出现。"""
        timer = _FocusTimer("idle")
        _, page = _focus_page(monkeypatch, timer)
        page._focus_card.set_status_provider(page._focus_status)
        assert page._focus_card.is_active() is False

        page._start_focus(25)
        assert page._focus_card.is_active() is True
        assert page._focus_card.clock_text() == "25:00"

    def test_buttons_drive_the_shared_timer(self, monkeypatch):
        timer = _FocusTimer("running", 600, 0.6)
        _, page = _focus_page(monkeypatch, timer)
        page._focus_card.set_status_provider(page._focus_status)

        page._on_focus_pause()
        assert timer.calls == [("pause",)]
        assert page._focus_card.title_text() == "专注已暂停"

        page._on_focus_resume()
        assert timer.calls[-1] == ("resume",)

        page._on_focus_stop()
        assert timer.calls[-1] == ("stop",)
        assert page._focus_card.is_active() is False

    def test_reload_does_not_re_enable_the_button_mid_session(self, monkeypatch):
        """刷新页面不能把「专注中」的按钮重新变回可点。

        不修的话会出现「卡里写着专注中、按钮写着开始」的自相矛盾界面。
        """
        timer = _FocusTimer("running", 600, 0.6)
        _, page = _focus_page(monkeypatch, timer)
        page._focus_card.set_status_provider(page._focus_status)
        page.reload()
        assert page._btn_focus.isEnabled() is False
        assert page._btn_focus.text() == "专注中…"

    def test_failure_reasons_are_told_apart(self, monkeypatch):
        """「番茄钟没加载」和「已经在跑」要分开说 —— 合一句用户不知道该修什么。"""
        _, page = _focus_page(monkeypatch, None)
        page._start_focus(25)
        assert "番茄钟插件未加载" in page._status.text()

        timer = _FocusTimer("running", 600, 0.6)
        _, page2 = _focus_page(monkeypatch, timer)
        page2._start_focus(25)
        assert "已经在跑" in page2._status.text()


class TestTodayAdviceSummary:
    """建议区的「总结」段（P2.18）。"""

    def test_summary_is_rendered_with_the_cards(self, monkeypatch):
        _, page = _focus_page(monkeypatch, None)
        page.set_advice(_ADVICE_WITH_SUMMARY)

        assert page._summary.has_summary() is True
        assert "深度工作只占 2 小时" in page._summary.summary()
        assert page._cards[0].isHidden() is False
        assert page._cards[0].headline() == "上午被切成 4 段"
        assert page._cards[1].isHidden() is True

    def test_legacy_bare_array_still_renders_without_a_summary(self, monkeypatch):
        """旧缓存（裸数组）升级后照样要能读 —— 没有总结是正常的，不是坏了。"""
        _, page = _focus_page(monkeypatch, None)
        page.set_advice('[{"headline": "上午被切成 4 段"}]')

        assert page._summary.has_summary() is False
        assert page._cards[0].isHidden() is False
        assert page._cards[0].headline() == "上午被切成 4 段"

    def test_plain_text_advice_shows_no_summary(self, monkeypatch):
        """大白话走原样显示那条路，硬塞总结会和正文重复。"""
        _, page = _focus_page(monkeypatch, None)
        page.set_advice("今天挺忙的\n上午写代码")

        assert page._summary.has_summary() is False
        assert "今天挺忙的" in page._raw.toPlainText()

    def test_summary_is_hidden_while_analyzing(self, monkeypatch):
        _, page = _focus_page(monkeypatch, None)
        page.set_advice(_ADVICE_WITH_SUMMARY)
        page.set_analyzing(True)
        assert page._summary.has_summary() is False
        assert page._cards[0].isHidden() is True

    def test_summary_survives_ignoring_every_card(self, monkeypatch):
        """建议被忽略光了，总结还该在 —— 它说的是今天的状态，不是建议的附属品。"""
        p, page = _focus_page(monkeypatch, None)
        page.set_advice(_ADVICE_WITH_SUMMARY)
        card = page._cards[0]
        page._on_card_decided(card.advice(), ACTION_IGNORE)

        assert page._cards[0].isHidden() is True
        assert page._summary.has_summary() is True

    def test_empty_json_result_is_shown_raw_not_as_a_fake_card(self, monkeypatch):
        """模型回 `[]` 时不该造出一条内容是 `[]` 的建议卡。"""
        _, page = _focus_page(monkeypatch, None)
        page.set_advice("[]")
        assert page._cards[0].isHidden() is True
        assert page._summary.has_summary() is False
        assert page._raw.isHidden() is False


class TestPluginStructuredReport:
    """插件把缓存解析成「总结 + 建议」时，过滤与总结都不能丢。"""

    def test_report_keeps_the_summary_and_filters_ignored(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        p._store.save_advice("day", p._data_signature(1), _ADVICE_WITH_SUMMARY)

        report = p.structured_report(1)
        assert report.summary.startswith("今天深度工作只占")
        assert len(report.advices) == 1

        p.ignore_advice(report.advices[0].fingerprint)
        after = p.structured_report(1)
        assert after.advices == ()
        assert after.summary == report.summary, "忽略建议不该把总结一起吃掉"

    def test_structured_advice_still_returns_a_plain_list(self, monkeypatch):
        """老调用方（对话框）还在用 `structured_advice` —— 契约不能变。"""
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        p._store.save_advice("day", p._data_signature(1), _ADVICE_WITH_SUMMARY)
        got = p.structured_advice(1)
        assert isinstance(got, list) and len(got) == 1
        assert got[0].headline == "上午被切成 4 段"

    def test_empty_cache_gives_an_empty_report(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        assert p.structured_report(1) == AdviceReport()


# ---------------------------------------------------------------- 趋势页（P2.14）


def _trend_page(app):
    from presentation.control_center import ControlCenter, reset_instance

    reset_instance()
    cc = ControlCenter(app=app)
    return next(p for p in cc._pages if p.title == "趋势")


def _seed_days(plugin, rows) -> None:
    """往插件库里塞**跨天**的记录（趋势页按自然日聚合，靠它出数）。

    `rows` 每项 `(days_ago, hour, minute, minutes, app, category)`。
    锚点用 `day_start(now - n*86400)` 而不是 `now - n*86400` ——
    后者会落到「昨天这个时刻」，跨午夜时自然日桶就抖了。
    """
    now = time.time()
    for days_ago, hour, minute, minutes, app_name, cat in rows:
        start = day_start(now - days_ago * DAY_SECONDS) + hour * 3600 + minute * 60
        plugin._store.add_segment(app_name, cat, start, start + minutes * 60)


class TestTrendPage:
    """趋势页（P2.14）—— 范围切换 / 每日柱状图 / 周期对比 / 打断时段。

    守的是「页面的数字与结论来自真实分段」以及「上周期为空时不说假话」。
    """

    def test_page_is_registered_under_data_group(self):
        from presentation.control_center import NAV_GROUPS, NAV_ITEMS

        assert "趋势" in [label for _, label, _ in NAV_ITEMS]
        data = next(items for name, items in NAV_GROUPS if name == "数据")
        # 「协同记录」是 v1.8.0 新增的决策证据链页 —— 它属于数据组：
        # 「我今天干得怎么样」和「我凭什么同意 AI 的建议」是同一批数据的两面。
        # 「应用分类」（v1.9.0）同样属于数据组：它纠正的是**同一批记录的类别**，
        # 与「今日 / 趋势」读的是同一份 segments，只是入口不同。
        assert [label for _, label, _ in data] == \
            ["今日", "趋势", "应用分类", "协同记录"]

    def test_default_range_is_seven_days(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        page = _trend_page(types.SimpleNamespace(plugin_manager=_PM(p)))
        assert page.selected_days() == 7

    def test_degrades_without_plugin(self):
        page = _trend_page(types.SimpleNamespace(plugin_manager=_PM(None)))
        assert page._empty.isHidden() is False
        assert "插件未加载" in page._empty.title()
        assert page._dashboard.isHidden() is True

    def test_empty_state_when_no_data(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        page = _trend_page(types.SimpleNamespace(plugin_manager=_PM(p)))
        assert page._dashboard.isHidden() is True
        assert "还没有记录" in page._empty.title()

    def test_tiles_use_real_segments(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_days(p, [
            (1, 9, 0, 60, "code.exe", WORK_CATEGORY),
            (2, 9, 0, 120, "code.exe", WORK_CATEGORY),
        ])
        page = _trend_page(types.SimpleNamespace(plugin_manager=_PM(p)))

        assert page._dashboard.isHidden() is False
        assert page._tiles["total"].value() == human_duration(3 * 3600)
        assert page._tiles["focus"].value() == human_duration(3 * 3600)
        assert page._tiles["daily"].value() == human_duration(3 * 3600 / 7)

    def test_overview_uses_the_same_board_as_today(self, monkeypatch):
        """趋势页的概览要与「今日」用**同一套**台面 —— 两个核心页的
        头条区必须长一样，否则用户得学两遍。"""
        from PySide6.QtWidgets import QFrame

        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_days(p, [(1, 9, 0, 60, "code.exe", WORK_CATEGORY)])
        page = _trend_page(types.SimpleNamespace(plugin_manager=_PM(p)))

        boards = page.findChildren(QFrame, "overviewBoard")
        assert len(boards) == 1
        assert boards[0].title() == "本周期概览"
        for key, tile in page._tiles.items():
            assert boards[0].tile(key) is tile

        primaries = [k for k, t in page._tiles.items() if t.is_primary()]
        assert primaries == ["total"], primaries

    def test_bar_chart_has_one_bar_per_day(self, monkeypatch):
        """柱子数必须 = 天数 —— 缺一天会让「周三和周五挨在一起」，
        看起来像连续两天都在工作。"""
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_days(p, [(1, 9, 0, 60, "code.exe", WORK_CATEGORY)])
        page = _trend_page(types.SimpleNamespace(plugin_manager=_PM(p)))
        assert page._chart.count() == 7

    def test_range_switch_changes_bar_count(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_days(p, [(1, 9, 0, 60, "code.exe", WORK_CATEGORY)])
        page = _trend_page(types.SimpleNamespace(plugin_manager=_PM(p)))

        page._seg_range.set_index(1, emit=True)        # 切到「近 30 天」
        assert page.selected_days() == 30
        assert page._chart.count() == 30

    def test_asks_plugin_for_double_range(self, monkeypatch):
        """对比要用上周期，所以必须取 **2 倍**天数。

        只取 1 倍时上周期恒为空 —— 页面不会报错，只会一直说「无法比较」，
        功能看起来「做了」，实际永远不生效。
        """
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        asked = []
        real = p.segments_for

        def spy(days):
            asked.append(days)
            return real(days)

        monkeypatch.setattr(p, "segments_for", spy)
        _seed_days(p, [(1, 9, 0, 60, "code.exe", WORK_CATEGORY)])
        page = _trend_page(types.SimpleNamespace(plugin_manager=_PM(p)))

        assert 14 in asked, "近 7 天要取 14 天（本周期 + 上周期）"
        page._seg_range.set_index(1, emit=True)
        assert asked[-1] == 60, "近 30 天要取 60 天"

    def test_category_rank_uses_real_segments(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_days(p, [
            (1, 9, 0, 60, "code.exe", WORK_CATEGORY),
            (1, 11, 0, 30, "chrome.exe", "浏览"),
        ])
        page = _trend_page(types.SimpleNamespace(plugin_manager=_PM(p)))
        assert page._rank.row_count() == 2

    def test_category_rank_counts_only_this_period(self, monkeypatch):
        """「时间构成」只能统计**本周期**。

        趋势页向插件要 `days * 2` 天（上周期是给对比用的）。拿这份混合列表
        直接算类别构成，同一页上「本周期总时长」是 6 天、「时间构成」却是
        12 天 —— 两个数字互相矛盾，而用户看不出来（P2.14 目检发现：
        概览 159 小时，时间构成 236 小时）。
        """
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        rows = []
        for d in range(1, 7):                       # 本周期：每天 1 小时「工作」
            rows.append((d, 9, 0, 60, "code.exe", WORK_CATEGORY))
        for d in range(7, 13):                      # 上周期：每天 2 小时「浏览」
            rows.append((d, 9, 0, 120, "chrome.exe", "浏览"))
        _seed_days(p, rows)
        page = _trend_page(types.SimpleNamespace(plugin_manager=_PM(p)))

        assert page._tiles["total"].value() == human_duration(6 * 3600)
        assert page._rank.row_count() == 1, "上周期只该出现在「对比」那句话里"
        assert page._rank.name_at(0) == WORK_CATEGORY
        assert page._rank.value_text_at(0) == human_duration(6 * 3600)

    def test_hour_chart_counts_only_this_period(self, monkeypatch):
        """按小时柱状图同理 —— 数两遍会把「平均每天 N 次」说大一倍。"""
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        rows = []
        for d in range(1, 7):                       # 本周期：每天 10 点切 1 次
            rows += [(d, 10, 0, 10, "a.exe", WORK_CATEGORY),
                     (d, 10, 10, 10, "b.exe", "沟通")]
        for d in range(7, 13):                      # 上周期：每天 10 点切 3 次
            rows += [(d, 10, 0, 5, "c.exe", WORK_CATEGORY),
                     (d, 10, 5, 5, "d.exe", "沟通"),
                     (d, 10, 10, 5, "e.exe", WORK_CATEGORY),
                     (d, 10, 15, 5, "f.exe", "沟通")]
        _seed_days(p, rows)
        page = _trend_page(types.SimpleNamespace(plugin_manager=_PM(p)))

        assert page._hours.value_at(10) == 6.0, "只该数本周期那 6 次"
        assert "10:00–11:00" in page._hours_hint.text()
        assert "24 次" not in page._hours_hint.text(), "把上周期也算进来了"

    def test_hour_chart_covers_full_day_and_highlights_peak(self, monkeypatch):
        """24 个桶一个不能少 —— 只有 16 点有数据时也必须画出完整的 24 根。"""
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_days(p, [
            (1, 10, 0, 10, "a.exe", WORK_CATEGORY),
            (1, 10, 10, 10, "b.exe", "沟通"),          # 10:10 切
            (1, 16, 0, 10, "c.exe", WORK_CATEGORY),
            (1, 16, 10, 10, "d.exe", "沟通"),          # 16:10 切
            (1, 16, 20, 10, "e.exe", WORK_CATEGORY),   # 16:20 切
        ])
        page = _trend_page(types.SimpleNamespace(plugin_manager=_PM(p)))

        assert page._hours.count() == HOURS_PER_DAY
        assert page._hours.highlight() == 16
        assert page._hours.value_at(16) == 3.0
        assert page._hours.value_at(10) == 1.0
        assert page._hours.value_at(3) == 0.0
        assert "16:00–17:00" in page._hours_hint.text()

    def test_compare_line_says_so_when_previous_is_empty(self, monkeypatch):
        """只有本周期数据时，页面必须说「无法比较」而不是编一个百分比。"""
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_days(p, [(1, 9, 0, 60, "code.exe", WORK_CATEGORY)])
        page = _trend_page(types.SimpleNamespace(plugin_manager=_PM(p)))
        text = page._compare.text()
        assert "无法比较" in text
        assert "%" not in text

    def test_compare_line_reports_growth(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_days(p, [
            (1, 9, 0, 60, "code.exe", WORK_CATEGORY),      # 本周期 1h
            (8, 9, 0, 30, "code.exe", WORK_CATEGORY),      # 上周期 30m
        ])
        page = _trend_page(types.SimpleNamespace(plugin_manager=_PM(p)))
        text = page._compare.text()
        assert "多" in text
        assert "100%" in text

    def test_footer_reflects_configured_retention(self, monkeypatch):
        """保留天数从配置读 —— 页面不能写死一个数字。

        只在**保留天数少于所选范围**时才出现（那是真的会影响读图的信息：
        更早的日子没数据，不说清就会被读成「那几天没干活」）。
        """
        p, _ = _quiet_plugin(
            monkeypatch,
            {"activity.enabled": True, "activity.retention_days": 7},
        )
        p.on_ui_ready(p.app)
        assert p.retention_days() == 7
        _seed_days(p, [(1, 9, 0, 60, "code.exe", WORK_CATEGORY)])
        page = _trend_page(types.SimpleNamespace(plugin_manager=_PM(p)))
        # 默认范围就是 7 天，没超出保留期 → 不该有提示
        assert page._footer.text() == ""
        assert page._footer.isHidden()

        page._seg_range.set_index(1, emit=True)      # 近 30 天 > 保留 7 天
        assert not page._footer.isHidden(), "该提示时没提示"
        assert "7 天" in page._footer.text(), "保留天数没有从配置读，写死了"

    def test_retention_default_covers_longest_range(self, monkeypatch):
        """默认保留必须 ≥ 趋势页最长范围（30 天），否则那个视图开箱就是残缺的。"""
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        assert p.retention_days() >= 30


class TestFocusProgress:
    """常驻指示（托盘进度环）要的那一个数字 —— P2.14 第 5 步。

    托盘只该要一个数字，不该知道「深度工作 = 类别为『工作』的段之和」
    这条口径；否则又是两处口径各写一遍。
    """

    def test_disabled_reports_disabled_not_zero(self, monkeypatch):
        """关闭时 `enabled=False` —— 空环会被读成「今天一点没干」，
        而真相是「根本没在记录」。两件事对用户的含义完全不同。"""
        p, _ = _quiet_plugin(monkeypatch, {})
        p.on_ui_ready(p.app)
        got = p.focus_progress(1)
        assert got["enabled"] is False
        assert got["focus"] == 0.0
        assert got["ratio"] == 0.0
        assert got["goal"] == pytest.approx(240 * 60.0)

    def test_counts_work_category_only(self, monkeypatch):
        p, _ = _quiet_plugin(monkeypatch, {"activity.enabled": True})
        p.on_ui_ready(p.app)
        _seed_today(p, [
            (9 * 60, 60, "code.exe", WORK_CATEGORY),
            (10 * 60, 60, "chrome.exe", "浏览"),
        ])
        got = p.focus_progress(1)
        assert got["enabled"] is True
        assert got["focus"] == pytest.approx(3600.0), "只有「工作」算深度工作"
        assert got["ratio"] == pytest.approx(3600.0 / (240 * 60))

    def test_ratio_caps_at_one(self, monkeypatch):
        """超额完成也是 1.0 —— 大于 1 的弧在 Qt 里会绕回去画成一小段。"""
        p, _ = _quiet_plugin(
            monkeypatch,
            {"activity.enabled": True, "activity.focus_goal_minutes": 60},
        )
        p.on_ui_ready(p.app)
        _seed_today(p, [(9 * 60, 120, "code.exe", WORK_CATEGORY)])
        got = p.focus_progress(1)
        assert got["goal"] == pytest.approx(3600.0)
        assert got["focus"] == pytest.approx(7200.0)
        assert got["ratio"] == 1.0

    def test_zero_goal_is_clamped(self, monkeypatch):
        """`0` 是合法配置值，但会让分母为零 —— 夹到至少 1 分钟。"""
        p, _ = _quiet_plugin(
            monkeypatch,
            {"activity.enabled": True, "activity.focus_goal_minutes": 0},
        )
        p.on_ui_ready(p.app)
        assert p.focus_goal_seconds() == pytest.approx(60.0)

    def test_goal_reads_config(self, monkeypatch):
        p, _ = _quiet_plugin(
            monkeypatch,
            {"activity.enabled": True, "activity.focus_goal_minutes": 90},
        )
        p.on_ui_ready(p.app)
        assert p.focus_goal_seconds() == pytest.approx(90 * 60.0)


class TestTrendPageText:
    """趋势页那几句话（纯函数）—— 说错话比画错图更难被发现。"""

    def test_day_ticks_sit_on_bar_centers(self):
        """刻度落在柱子的**中心**而不是左边缘 ——
        标在边缘会让人以为刻度对应的是柱子的开始时刻。"""
        from presentation.control_center import _day_ticks

        rows = [{"day": f"10-{i:02d}", "weekday": "周一"} for i in range(1, 8)]
        ticks = _day_ticks(rows)
        assert len(ticks) == 7
        for i, (fraction, text) in enumerate(ticks):
            assert fraction == pytest.approx((i + 0.5) / 7)
            assert text.startswith(rows[i]["day"])

    def test_day_ticks_thin_out_for_long_ranges(self):
        """30 天全标会糊成一片 —— 但要保住首尾，否则读不出区间。"""
        from presentation.control_center import _day_ticks

        rows = [{"day": f"{i:02d}", "weekday": "周一"} for i in range(30)]
        ticks = _day_ticks(rows)
        assert 3 <= len(ticks) <= 8
        assert ticks[0][0] == pytest.approx(0.5 / 30)
        assert ticks[-1][0] == pytest.approx(29.5 / 30)

    def test_day_ticks_empty(self):
        from presentation.control_center import _day_ticks

        assert _day_ticks([]) == ()

    def test_compare_text_no_percent_when_previous_is_empty(self):
        from presentation.control_center import _compare_text

        text = _compare_text(
            {"previous": {"total": 0.0}, "delta_seconds": 3600.0,
             "delta_ratio": None}, 7
        )
        assert "无法比较" in text
        assert "%" not in text, "上周期为 0 时不能编出一个百分比"

    def test_compare_text_reports_direction_and_percent(self):
        from presentation.control_center import _compare_text

        up = _compare_text(
            {"previous": {"total": 3600.0}, "delta_seconds": 1800.0,
             "delta_ratio": 0.5}, 7
        )
        assert "多" in up and "50%" in up
        down = _compare_text(
            {"previous": {"total": 3600.0}, "delta_seconds": -1800.0,
             "delta_ratio": -0.5}, 7
        )
        assert "少" in down and "50%" in down

    def test_compare_text_calls_tiny_delta_flat(self):
        """差几秒钟不该被说成「多了 1%」—— 那是噪声，不是趋势。"""
        from presentation.control_center import _compare_text

        text = _compare_text(
            {"previous": {"total": 3600.0}, "delta_seconds": 10.0,
             "delta_ratio": 0.003}, 7
        )
        assert "持平" in text
        assert "%" not in text

    def test_hour_text_handles_no_switches(self):
        from presentation.control_center import _hour_text

        assert "没有记录到应用切换" in _hour_text(None, [0] * 24, 7)

    def test_hour_text_names_peak_and_average(self):
        from presentation.control_center import _hour_text

        buckets = [0] * 24
        buckets[10] = 14
        text = _hour_text(10, buckets, 7)
        assert "10:00–11:00" in text
        assert "14 次" in text
        assert "2.0 次" in text              # 14 / 7

    def test_footer_warns_only_when_range_exceeds_retention(self):
        """底部那行**只在保留天数不够时**才出现 —— 够用就闭嘴。

        「数据只在本机，保留最近 N 天，不出网」那句在隐私卡片 / 今日页
        已经说过，每页重复一遍是噪音，且不帮助理解眼前这张图。
        """
        from presentation.control_center import _trend_footer

        assert "7 天" in _trend_footer(7, 30)     # 保留 7 天 < 所选 30 天 → 有话说
        assert _trend_footer(30, 30) == ""        # 刚好够用 → 不打扰
        assert _trend_footer(30, 7) == ""
        assert "不出网" not in _trend_footer(7, 30)


# ================================================================
# P2.19：页面上每个「开始专注」入口都要跟着状态变
# ================================================================

#: 两条带动作的建议。**必须是两条** —— 只留一条就测不出「只锁了第一张」
#: 这种半成品实现（用户点的偏偏可能是第二张）。
_ADVICE_TWO_CARDS = (
    '{"summary": "今天偏碎",'
    ' "advices": ['
    '   {"headline": "上午被切成 4 段", "evidence": ["切换 4 次"],'
    '    "action": {"kind": "focus", "minutes": 45}},'
    '   {"headline": "下午节奏更碎", "evidence": ["切换 11 次"],'
    '    "action": {"kind": "focus", "minutes": 25}}]}'
)


class TestTodayFocusEntries:
    """今日页上的每个专注入口必须反映**同一个**状态（P2.19）。

    用户报的 bug 正在这里：点了建议卡上的「开始 90 分钟专注」之后，
    顶部按钮变了、倒计时卡也出来了，**唯独他点的那张卡上的按钮一动不动**
    —— 看不出点上了，还能再点一次。
    """

    @staticmethod
    def _cards(page):
        """**卡片本身**可见的那些。

        判据用 `isHidden()` 而不是按钮的可见性：没被填建议的卡是
        `card.hide()` 收起来的，但它的按钮自己并没有被隐藏 ——
        只看按钮会把这些空卡也算进来，断言就变成了「4 张卡都锁了」。
        """
        return [c for c in page._cards if not c.isHidden()]

    def test_all_cards_lock_while_a_session_runs(self, monkeypatch):
        timer = _FocusTimer("running", 12 * 60 + 34, 0.5)
        _, page = _focus_page(monkeypatch, timer)
        page.set_advice(_ADVICE_TWO_CARDS)

        assert page._btn_focus.isEnabled() is False
        assert page._btn_focus.text() == "专注中…"
        cards = self._cards(page)
        assert len(cards) == 2, "两条建议都该有动作按钮"
        for card in cards:
            assert card.action_enabled() is False
            assert card.action_text() == "专注中…"

    def test_cards_stay_clickable_when_idle(self, monkeypatch):
        _, page = _focus_page(monkeypatch, _FocusTimer("idle"))
        page.set_advice(_ADVICE_TWO_CARDS)

        assert page._btn_focus.isEnabled() is True
        for card in self._cards(page):
            assert card.action_enabled() is True
            assert card.action_text().startswith("开始 ")

    def test_a_fresh_card_lands_on_the_current_state(self, monkeypatch):
        """专注已经在跑的时候才生成建议 —— 新卡片必须**直接**是锁定的。"""
        timer = _FocusTimer("running", 600, 0.6)
        _, page = _focus_page(monkeypatch, timer)
        page.set_advice("")
        page.set_advice(_ADVICE_TWO_CARDS)

        for card in self._cards(page):
            assert card.action_enabled() is False

    def test_paused_is_reflected_on_every_entry(self, monkeypatch):
        timer = _FocusTimer("running", 600, 0.6)
        _, page = _focus_page(monkeypatch, timer)
        page._focus_card.set_status_provider(page._focus_status)
        page.set_advice(_ADVICE_TWO_CARDS)

        page._on_focus_pause()
        assert page._btn_focus.text() == "已暂停"
        for card in self._cards(page):
            assert card.action_text() == "已暂停"

    def test_stopping_gives_every_entry_back(self, monkeypatch):
        timer = _FocusTimer("running", 600, 0.6)
        _, page = _focus_page(monkeypatch, timer)
        page._focus_card.set_status_provider(page._focus_status)
        page.set_advice(_ADVICE_TWO_CARDS)

        page._on_focus_stop()
        assert page._btn_focus.isEnabled() is True
        for card in self._cards(page):
            assert card.action_enabled() is True
            assert card.action_text().startswith("开始 ")

    def test_the_card_button_cannot_restart_the_session(self, monkeypatch):
        """真判据：锁定期间点它**不会**再发一次启动请求。

        只看 `isEnabled()` 会漏掉「外观灰了但槽里没拦」的实现。
        """
        timer = _FocusTimer("running", 600, 0.6)
        _, page = _focus_page(monkeypatch, timer)
        page.set_advice(_ADVICE_TWO_CARDS)

        seen: list = []
        page._cards[0].decided.connect(lambda a, act: seen.append((a, act)))
        page._cards[0]._btn_action.click()
        assert seen == []
        assert timer.calls == []

    def test_no_plugin_keeps_the_button_disabled(self):
        """降级路径：没有活动洞察插件 → 按钮**永远**不可用。

        即使当前不在专注（idle）也不能点亮 —— 那个按钮点下去只会弹
        「插件未加载」，是个可点却必然失败的按钮。

        反向验证发现第一版是**假测试**：只在构造后断言，而当时
        `_show_cards` 会顺手同步一次，于是把「插件缺失」的禁用覆盖掉了，
        测试反而在断言被覆盖后的结果。同步改成只由状态变化 / reload 触发后，
        这里必须**真的把状态推过去**才能测到那个分支。
        """
        page = _page(types.SimpleNamespace(
            plugin_manager=_PM(None), timer=_FocusTimer("idle")))
        page._on_focus_state("idle")
        assert page._btn_focus.isEnabled() is False


class TestTomatoPageFeedback:
    """番茄钟页的按钮也要跟着变，状态行要自己刷新（P2.19）。

    原来这一页只在切页 / 点按钮时刷一次状态：点完「开始」按钮还写着
    「开始一个番茄」、还能反复点，旁边那行小字也定在 `running` 上不动 ——
    同一功能在对话框里是活的、在页面里是死的。
    """

    @staticmethod
    def _tomato(timer):
        from presentation.control_center import TomatoPage

        return TomatoPage(types.SimpleNamespace(
            app=types.SimpleNamespace(timer=timer)))

    def test_the_button_says_how_long(self):
        page = self._tomato(_FocusTimer("idle"))
        page._work.setValue(45)
        assert page._btn_start.text() == "开始 45 分钟专注"
        assert page._btn_start.isEnabled() is True

    def test_the_button_follows_a_running_session(self):
        page = self._tomato(_FocusTimer("running"))
        page._refresh_status()
        assert page._btn_start.text() == "专注中…"
        assert page._btn_start.isEnabled() is False

    def test_the_button_comes_back_after_stopping(self):
        timer = _FocusTimer("running")
        page = self._tomato(timer)
        page._refresh_status()
        timer.status["state"] = "idle"
        page._refresh_status()
        assert page._btn_start.isEnabled() is True
        assert page._btn_start.text().startswith("开始 ")

    def test_the_status_line_is_in_chinese(self):
        """原来把 `running` / `paused` 这种英文枚举直接印给用户看。"""
        page = self._tomato(_FocusTimer("running"))
        page._refresh_status()
        text = page._lbl_status.text()
        assert "进行中" in text
        assert "running" not in text

    def test_a_timer_with_missing_fields_does_not_crash(self):
        """计时器是可选插件，字段缺一个不该把整页打崩。

        断言必须**排除**「状态不可用」这个兜底文案 —— 只断言「有字」是
        假测试：把取值改成硬索引 `st['today_count']`，异常照样被 catch 住、
        界面照样有字，改坏了也绿。
        """

        class _Thin:
            @staticmethod
            def get_status():
                return {"state": "running"}

        page = self._tomato(_Thin())
        page._refresh_status()
        text = page._lbl_status.text()
        assert text != "状态不可用", "缺字段被当成「读不到状态」了"
        assert "进行中" in text
        assert "今日完成 0 个" in text

    def test_no_timer_disables_the_button(self):
        page = self._tomato(None)
        page._refresh_status()
        assert page._btn_start.isEnabled() is False
        assert "未加载" in page._lbl_status.text()

    def test_polling_runs_only_while_the_page_is_visible(self):
        """控制中心常年开着 —— 看不见的倒计时不该每秒读一次状态。"""
        from PySide6.QtGui import QHideEvent, QShowEvent

        page = self._tomato(_FocusTimer("running"))
        page.showEvent(QShowEvent())
        assert page._tick.isActive() is True
        page.hideEvent(QHideEvent())
        assert page._tick.isActive() is False
