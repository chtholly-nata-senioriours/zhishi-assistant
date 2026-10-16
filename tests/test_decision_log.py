# -*- coding: utf-8 -*-
"""人机协同决策留痕（P1-4）—— 证据链的契约测试。

守的是三件事：
    1. **留痕在动作那一刻固化**：依据、上下文、影响三样都要有，
       而且上下文只含聚合数字（窗口标题这类字段连键都进不去）。
    2. **采纳与忽略走同一条路**：两个按钮都留痕，且采纳记的是**实际结果**
       （计时已经在跑时不能写成「已开始」——那是假证据）。
    3. **可审计**：留痕能落库、能按动作过滤、能导出成一份人可读的文本，
       并且随「清空行为数据」一起被删掉。

运行:
    python tests/test_decision_log.py
    pytest tests/test_decision_log.py -v
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import types  # noqa: E402

import pytest  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from engine.activity import (  # noqa: E402
    ACTION_ADOPT,
    ACTION_IGNORE,
    CONTEXT_KEYS,
    ActivityStore,
    Advice,
    AdviceAction,
    DecisionNote,
    build_context,
    build_note,
    format_context,
    format_notes,
)
from presentation.control_center import DecisionLogPage  # noqa: E402


# ============================================================
# 测试替身
# ============================================================

def _advice(headline="上午的深度工作被切成 4 段", minutes=45, evidence=(
        "微信在 08:00-12:00 打断 9 次", "VS Code 最长连续 1h30m")):
    return Advice(
        headline=headline,
        evidence=evidence,
        action=(AdviceAction(kind="focus", minutes=minutes, label=f"开始 {minutes} 分钟专注")
                if minutes else AdviceAction()),
    )


def _segments(count=3, seconds=600.0):
    return [{"app": "code.exe", "category": "工作", "start_at": 1000.0 + i * 100,
             "end_at": 1000.0 + i * 100 + seconds, "seconds": seconds}
            for i in range(count)]


class FakeCenter:
    """够页面用的最小 center。"""

    def __init__(self, plugin=None):
        self.app = types.SimpleNamespace(
            plugin_manager=types.SimpleNamespace(get_plugin=lambda name: plugin))
        self.warnings: list = []
        self.infos: list = []

    def confirm(self, *_a, **_k) -> bool:
        return True

    def info(self, title, text=""):
        self.infos.append((title, text))

    def warn(self, title, text=""):
        self.warnings.append((title, text))


# ============================================================
# ① 纯函数：留痕长什么样
# ============================================================

class TestBuildNote:

    def test_adopt_note_carries_basis_context_and_impact(self):
        note = build_note(_advice(), ACTION_ADOPT,
                          context=build_context(1, _segments()),
                          outcome={"focus_started": True, "focus_minutes": 45},
                          now=1000.0)
        assert note.action == ACTION_ADOPT
        assert note.action_label == "采纳"
        assert note.at == 1000.0
        assert "微信在 08:00-12:00 打断 9 次" in note.basis
        assert "动作：开始 45 分钟专注" in note.basis, "采纳要把「同意了什么动作」记进依据"
        assert note.context["segments"] == 3
        assert note.context["scope"] == "今日"
        assert "已开始 45 分钟专注" in note.impact

    def test_ignore_note_says_what_it_does_not_change(self):
        note = build_note(_advice(), ACTION_IGNORE, context=build_context(1, _segments()))
        assert note.action_label == "忽略"
        assert "不再出现" in note.impact
        # 「不影响本机记录」这句是防误解的：用户会以为忽略等于删数据
        assert "不影响本机活动记录" in note.impact

    def test_context_is_whitelisted(self):
        """窗口标题这类字段**连键都进不去** —— 白名单是结构性保证。"""
        raw = {"scope": "今日", "segments": 2, "window_title": "私密文档.docx",
               "keys": "asdf", "clipboard": "银行卡号"}
        ctx = build_context(1, _segments(), generated_by="x")
        assert "window_title" not in ctx
        merged = build_note(_advice(), ACTION_IGNORE, context={**ctx, **raw}).context
        assert "window_title" not in merged
        assert "clipboard" not in merged
        assert set(merged) <= set(CONTEXT_KEYS)

    def test_context_keeps_aggregates_only(self):
        """上下文里不该出现任何**逐段的原始数据**（app 名、起止）。"""
        ctx = build_context(1, _segments())
        assert ctx["segments"] == 3
        assert ctx["tracked_seconds"] == 1800
        assert isinstance(ctx["range"], list) and len(ctx["range"]) == 2
        flat = repr(ctx)
        assert "code.exe" not in flat, "上下文只放聚合数字，不放应用名"

    def test_stale_and_focus_flags_are_recorded(self):
        ctx = build_context(7, _segments(), advice_created_at=1234.0,
                            advice_stale=True, focus_running=True)
        assert ctx["scope"] == "近 7 天"
        assert ctx["advice_created_at"] == 1234.0
        assert ctx["advice_stale"] is True
        assert ctx["focus_running"] is True
        text = format_context(ctx)
        assert "生成后数据已变化" in text
        assert "决定时专注正在进行" in text

    def test_false_flags_are_recorded_as_false_not_omitted(self):
        """**只测 True 会让「只记 True」的实现照样全绿**。

        两个布尔必须**总是**记（含 False）：留痕要能区分「当时没在专注」与
        「当时没检查」—— 只记 True 的话，读的人分不出这两种，
        一条「没写 focus_running」的记录到底是哪种情况就成了悬案。
        """
        ctx = build_context(1, _segments())
        assert ctx["advice_stale"] is False, "False 也要落键，不能因为等于假就省掉"
        assert ctx["focus_running"] is False
        text = format_context(ctx)
        assert "生成后数据未变化" in text
        assert "决定时专注未在进行" in text

    def test_empty_values_are_dropped_but_zero_and_false_are_kept(self):
        """空值不留键，`0` / `False` 必须留下 —— 这是两个相反的取舍，各测一次。

        为什么空值要丢：`format_context` 里 `"segments" in ctx` 是**存在性**
        判断（正是为了保住 0），于是 `{"segments": None}` 一旦留下键，
        界面就会显示「现场 None 段记录」。
        为什么 0 要留：「现场 0 段记录」说明这条建议当时没有数据支撑，
        是事实；丢掉它，留痕就变成了「没检查」。
        """
        ctx = build_note(_advice(), ACTION_IGNORE, context={
            "segments": 0, "tracked_seconds": 0, "advice_stale": False,
            "focus_running": False, "scope": "", "summary": None, "range": [],
        }).context
        assert ctx["segments"] == 0
        assert ctx["tracked_seconds"] == 0
        assert ctx["advice_stale"] is False
        assert ctx["focus_running"] is False
        for gone in ("scope", "summary", "range"):
            assert gone not in ctx, f"{gone} 是空值，不该留下键"
        text = format_context(ctx)
        assert "现场 0 段记录" in text
        assert "None" not in text, "空值漏进上下文会在界面上显示成字面量 None"

    def test_unknown_action_is_rejected(self):
        with pytest.raises(ValueError):
            build_note(_advice(), "delete")

    def test_advice_without_fingerprint_is_rejected(self):
        with pytest.raises(ValueError):
            build_note(Advice(headline=""), ACTION_IGNORE)

    def test_adopt_without_started_is_not_recorded_as_started(self):
        """没跑起来就不能写成「已开始」—— 假证据比没有证据更糟。"""
        note = build_note(_advice(), ACTION_ADOPT,
                          outcome={"focus_started": False, "focus_minutes": 45})
        assert "未开始专注" in note.impact
        assert "已开始" not in note.impact

    def test_round_trip_through_dict(self):
        note = build_note(_advice(), ACTION_ADOPT, context=build_context(1, _segments()))
        again = DecisionNote.from_dict(note.to_dict())
        assert again == note

    def test_from_dict_rejects_unknown_action(self):
        assert DecisionNote.from_dict({"action": "rm -rf", "headline": "x"}) is None
        assert DecisionNote.from_dict(None) is None


# ============================================================
# ② 落库：可追溯、可过滤、可清空
# ============================================================

class TestStoreDecisions:

    @pytest.fixture()
    def store(self):
        s = ActivityStore(":memory:")
        yield s
        s.close()

    def test_record_and_read_back(self, store):
        note = build_note(_advice(), ACTION_IGNORE, context=build_context(1, _segments()))
        import json

        rid = store.record_decision(note.fingerprint, note.headline, note.action,
                                    json.dumps(note.to_dict(), ensure_ascii=False))
        assert rid > 0
        rows = store.decisions()
        assert len(rows) == 1
        assert rows[0]["headline"] == note.headline
        assert DecisionNote.from_dict(json.loads(rows[0]["note"])) == note

    def test_newest_first(self, store):
        import json

        for i, action in enumerate((ACTION_IGNORE, ACTION_ADOPT)):
            note = build_note(_advice(headline=f"第 {i} 条"), action)
            store.record_decision(note.fingerprint, note.headline, note.action,
                                  json.dumps(note.to_dict(), ensure_ascii=False),
                                  now=100.0 + i)
        rows = store.decisions()
        assert [r["headline"] for r in rows] == ["第 1 条", "第 0 条"]

    def test_filter_by_action(self, store):
        import json

        for action in (ACTION_IGNORE, ACTION_ADOPT, ACTION_IGNORE):
            note = build_note(_advice(), action)
            store.record_decision(note.fingerprint, note.headline, note.action,
                                  json.dumps(note.to_dict(), ensure_ascii=False))
        assert store.count_decisions() == 3
        assert store.count_decisions(ACTION_ADOPT) == 1
        assert store.count_decisions(ACTION_IGNORE) == 2
        assert len(store.decisions(action=ACTION_ADOPT)) == 1

    def test_clear_removes_decisions_too(self, store):
        """「清空行为数据」必须连留痕一起删 —— 它同样是用户行为的产物。"""
        import json

        note = build_note(_advice(), ACTION_IGNORE)
        store.record_decision(note.fingerprint, note.headline, note.action,
                              json.dumps(note.to_dict(), ensure_ascii=False))
        store.add_segment("code.exe", "工作", 0.0, 60.0)
        store.clear()
        assert store.count_decisions() == 0

    def test_clear_decisions_keeps_segments(self, store):
        import json

        note = build_note(_advice(), ACTION_IGNORE)
        store.record_decision(note.fingerprint, note.headline, note.action,
                              json.dumps(note.to_dict(), ensure_ascii=False))
        store.add_segment("code.exe", "工作", 0.0, 60.0)
        assert store.clear_decisions() == 1
        assert store.count() == 1


# ============================================================
# ③ 导出：给审计看的那一份
# ============================================================

class TestFormatNotes:

    def test_export_contains_every_section(self):
        adopt = build_note(_advice(), ACTION_ADOPT,
                           context=build_context(1, _segments()),
                           outcome={"focus_started": True, "focus_minutes": 45},
                           now=1000.0)
        ignore = build_note(_advice(headline="下午节奏变碎"), ACTION_IGNORE,
                            context=build_context(1, _segments()), now=2000.0)
        text = format_notes([adopt, ignore])
        assert "人机协同决策留痕" in text
        assert "共 2 条决定（采纳 1 / 忽略 1）" in text
        # 「该在的」用子串查……
        for piece in ("推荐依据", "上下文", "微信在 08:00-12:00 打断 9 次"):
            assert piece in text, piece
        # ……「不该在的」用精确常量查：表头那句说明里也有「影响范围」四个字，
        # 只查子串的话，把整行影响范围删掉照样全绿。
        assert f"影响范围：{adopt.impact}" in text
        assert f"影响范围：{ignore.impact}" in text
        assert "（未记录）" not in text, "两条留痕都记了影响范围，兜底文案不该出现"
        # 新的在前
        assert text.index("下午节奏变碎") < text.index("上午的深度工作被切成 4 段")

    def test_empty_export_is_still_a_valid_document(self):
        text = format_notes([])
        assert "共 0 条决定" in text


# ============================================================
# ④ 插件：两条路都留痕
# ============================================================

def _plugin(monkeypatch, values=None):
    """建一个已加载、采集已开启的插件（与 test_activity_advisor 同一套做法）。"""
    import extensions.system.activity_advisor.plugin as mod
    from extensions.system.activity_advisor.plugin import ActivityAdvisorPlugin

    class _Bus:
        def __init__(self):
            self.subs = {}

        def subscribe(self, name, fn):
            self.subs.setdefault(name, []).append(fn)

        def unsubscribe(self, name, fn):
            self.subs[name] = [f for f in self.subs.get(name, []) if f is not fn]

    class _Cfg:
        def __init__(self, vals):
            self.vals = dict(vals)
            self.saved = 0

        def get(self, key, default=None):
            return self.vals.get(key, default)

        def set(self, key, value):
            self.vals[key] = value

        def save(self):
            self.saved += 1

    monkeypatch.setattr(mod, "event_bus", _Bus())
    monkeypatch.setattr(mod, "ActivityStore", lambda: ActivityStore(":memory:"))
    p = ActivityAdvisorPlugin()
    p.app = types.SimpleNamespace(config=_Cfg(values or {"activity.enabled": True}))
    p.on_load(p.app)
    p.on_ui_ready(p.app)
    monkeypatch.setattr(p, "_idle", lambda: 0.0)
    monkeypatch.setattr(p, "_is_fullscreen", lambda: False)
    monkeypatch.setattr(p, "_is_timer_running", lambda: False)
    return p


class TestPluginDecisions:

    def test_ignore_writes_both_marker_and_note(self, monkeypatch):
        p = _plugin(monkeypatch)
        adv = _advice()
        ok, message = p.record_decision(adv, ACTION_IGNORE)
        assert ok, message
        assert adv.fingerprint in p.ignored_fingerprints()
        notes = p.decision_log()
        assert len(notes) == 1
        assert notes[0].action == ACTION_IGNORE
        assert "留档" in message

    def test_adopt_does_not_add_an_ignore_marker(self, monkeypatch):
        """采纳不该顺手把建议也屏蔽掉 —— 那是两件事。"""
        p = _plugin(monkeypatch)
        adv = _advice()
        ok, _ = p.record_decision(adv, ACTION_ADOPT)
        assert ok
        assert p.ignored_fingerprints() == set()
        assert len(p.decision_log()) == 1

    def test_note_uses_the_live_data_context(self, monkeypatch):
        p = _plugin(monkeypatch)
        # 用**现在**的时间戳：`segments_for(1)` 取的是「今天 00:00 起」，
        # 用 1970 的时间戳会被过滤掉，于是这条断言会假绿（现场 0 段也说得通）。
        now = time.time()
        p._store.add_segment("code.exe", "工作", now - 600, now)
        ok, _ = p.record_decision(_advice(), ACTION_ADOPT)
        assert ok
        ctx = p.decision_log()[0].context
        assert ctx["segments"] == 1
        assert ctx["tracked_seconds"] == 600
        assert ctx["generated_by"] == "activity_advisor"

    def test_unknown_action_is_refused(self, monkeypatch):
        """**必须是入口自己拦下的**，不能靠 `build_note` 抛异常兜底。

        判据用精确文案：写 `"未知" in message` 的话，`build_note` 的 ValueError
        被 catch 后拼出的「留痕失败：未知的决定类型…」也含这两个字 ——
        入口那层校验删掉照样全绿。同一件事有两个实现，等于两个都没验证。
        """
        p = _plugin(monkeypatch)
        ok, message = p.record_decision(_advice(), "like")
        assert not ok
        assert message == "未知的决定类型：like", message
        assert p.decision_log() == []

    def test_disabled_plugin_refuses_instead_of_pretending(self, monkeypatch):
        p = _plugin(monkeypatch, {"activity.enabled": False})
        ok, message = p.record_decision(_advice(), ACTION_ADOPT)
        assert not ok and "采集未开启" in message

    def test_decision_log_filters(self, monkeypatch):
        p = _plugin(monkeypatch)
        p.record_decision(_advice(headline="A"), ACTION_ADOPT)
        p.record_decision(_advice(headline="B"), ACTION_IGNORE)
        assert p.count_decisions() == 2
        assert p.count_decisions(ACTION_ADOPT) == 1
        assert [n.headline for n in p.decision_log(action=ACTION_IGNORE)] == ["B"]

    def test_export_decisions_is_readable_text(self, monkeypatch):
        p = _plugin(monkeypatch)
        p.record_decision(_advice(), ACTION_ADOPT)
        text = p.export_decisions()
        assert "人机协同决策留痕" in text
        assert "上午的深度工作被切成 4 段" in text


# ============================================================
# ⑤ 页面：能看、能筛、能导出
# ============================================================

def _page(plugin):
    center = FakeCenter(plugin)
    return DecisionLogPage(center, None), center


class TestDecisionLogPage:

    def test_rows_show_time_action_headline_and_impact(self, monkeypatch):
        p = _plugin(monkeypatch)
        p.record_decision(_advice(), ACTION_ADOPT,
                          outcome={"focus_started": True, "focus_minutes": 45})
        page, _ = _page(p)
        assert page._table.rowCount() == 1
        assert page._table.item(0, 1).text() == "采纳"
        assert page._table.item(0, 2).text() == "上午的深度工作被切成 4 段"
        assert "已开始 45 分钟专注" in page._table.item(0, 3).text()

    def test_detail_pane_shows_the_evidence(self, monkeypatch):
        p = _plugin(monkeypatch)
        p.record_decision(_advice(), ACTION_IGNORE)
        page, _ = _page(p)
        detail = page._detail.toPlainText()
        for piece in ("推荐依据", "微信在 08:00-12:00 打断 9 次", "影响范围", "建议指纹"):
            assert piece in detail, piece

    def test_filter_narrows_to_one_action(self, monkeypatch):
        p = _plugin(monkeypatch)
        p.record_decision(_advice(headline="A"), ACTION_ADOPT)
        p.record_decision(_advice(headline="B"), ACTION_IGNORE)
        page, _ = _page(p)
        assert page._table.rowCount() == 2

        page._filter.set_index(1, emit=True)      # 采纳
        assert page._table.rowCount() == 1
        assert page._table.item(0, 2).text() == "A"

        page._filter.set_index(2, emit=True)      # 忽略
        assert page._table.rowCount() == 1
        assert page._table.item(0, 2).text() == "B"

    def test_empty_state_when_no_decisions(self, monkeypatch):
        p = _plugin(monkeypatch)
        page, _ = _page(p)
        assert page._empty.isHidden() is False
        assert page._table.isHidden() is True
        assert "还没有决策记录" in page._empty.title()

    def test_table_and_empty_state_are_mutually_exclusive(self, monkeypatch):
        p = _plugin(monkeypatch)
        p.record_decision(_advice(), ACTION_ADOPT)
        page, _ = _page(p)
        assert page._empty.isHidden() is True
        assert page._table.isHidden() is False

    def test_empty_state_hides_the_detail_card_and_disables_export(self, monkeypatch):
        """「还没有决策记录」旁边不能同时挂着「完整留痕」卡和导出按钮。

        只藏表格是不够的：一边说没有记录、一边请你导出，用户只能理解为界面坏了。
        导出用**禁用**而不是隐藏（不跳版，也说明「这里本来有个功能」），
        「刷新」保持可用 —— 去今日页做一次决定再回来，就是这个空态的下一步。
        （这一处是目检 S17 抓到的：规格断言当时只钉了表格与空态互斥。）
        """
        p = _plugin(monkeypatch)
        page, _ = _page(p)
        assert page._detail_card.isHidden() is True
        assert page._btn_export.isEnabled() is False
        # 空态下按钮仍然存在（只是禁用）—— 隐藏会让布局跳一下
        assert page._btn_export.isHidden() is False

    def test_detail_card_and_export_come_back_with_data(self, monkeypatch):
        p = _plugin(monkeypatch)
        p.record_decision(_advice(), ACTION_ADOPT)
        page, _ = _page(p)
        assert page._detail_card.isHidden() is False
        assert page._btn_export.isEnabled() is True

    def test_detail_text_wraps_instead_of_being_clipped(self, monkeypatch):
        """上下文那行很长，**必须自动换行**，否则右边缘直接切掉。

        `QPlainTextEdit` 的默认是 `NoWrap`（与 `QTextEdit` 相反）——
        而这一页卖的正是「能逐条核对」，看不全等于没留痕。（目检 S17 抓到。）
        """
        from PySide6.QtWidgets import QPlainTextEdit

        p = _plugin(monkeypatch)
        p.record_decision(_advice(), ACTION_ADOPT)
        page, _ = _page(p)
        assert page._detail.lineWrapMode() == QPlainTextEdit.LineWrapMode.WidgetWidth

    def test_a_longer_note_gets_a_taller_detail_pane(self, monkeypatch):
        """详情区高度**跟着内容走**，不是钉死的一个数。

        固定高度的问题不是「不好看」：长短差得很远的两种留痕共用同一个高度，
        长的那个就永远要在盒子里滚 —— 而页面外面明明还有地方。
        判据用**比较**（长的 > 短的），不是「等于某个像素数」：
        后者会把字体 / DPI 变化也算成失败。

        ⚠ 必须 `show()` 过：高度按 `viewport().width()` 算换行，没布局过时
        宽度是几十像素，两个都会顶到上限 —— 那样断言会退化成 `460 > 460` 恒假。
        （这正是本项目那条规矩：UI 断言先问「没 show 过的控件上成立吗」。）
        """
        short = _advice(evidence=("一条证据",))
        long = _advice(evidence=("微信在 08:00-12:00 打断 9 次",
                                 "VS Code 最长连续 1h30m",
                                 "Chrome 与 VS Code 之间来回切换 7 次"))

        def _shown_page(advice):
            p = _plugin(monkeypatch)
            p.record_decision(advice, ACTION_IGNORE)
            page, _ = _page(p)
            page.resize(900, 700)
            page.show()
            app.processEvents()
            return page

        page_short = _shown_page(short)
        page_long = _shown_page(long)

        assert page_long._detail.height() > page_short._detail.height()
        # 也不能无限长：上限存在（一条超长留痕不该把整页顶出去）
        assert page_long._detail.height() <= page_long._DETAIL_MAX
        assert page_short._detail.height() >= page_short._DETAIL_MIN

    def test_summary_counts_both_kinds(self, monkeypatch):
        p = _plugin(monkeypatch)
        p.record_decision(_advice(headline="A"), ACTION_ADOPT)
        p.record_decision(_advice(headline="B"), ACTION_IGNORE)
        p.record_decision(_advice(headline="C"), ACTION_IGNORE)
        page, _ = _page(p)
        assert "共 3 条决定" in page._summary.text()
        assert "采纳 1" in page._summary.text()
        assert "忽略 2" in page._summary.text()

    def test_missing_plugin_degrades_without_crashing(self):
        page, _ = _page(None)
        assert page._table.rowCount() == 0
        assert "插件未加载" in page._summary.text()
        # 插件都没有，导出按钮更不该可点（点了只会弹一个「插件未加载」）
        assert page._btn_export.isEnabled() is False

    def test_export_without_records_warns_instead_of_writing(self, monkeypatch):
        """没有记录时**不能走到文件对话框** —— 那会让用户以为要导出一份空文件。

        判据必须落在「有没有弹保存框」上：`format_notes([])` 本来就会给出一份
        带标题的文档（导出物要自解释），拿「文本空不空」当守卫，
        这个分支永远不触发，而用户会走进一个保存空文件的对话框。
        """
        from presentation import control_center as cc

        opened: list = []
        monkeypatch.setattr(cc.QFileDialog, "getSaveFileName",
                            lambda *a, **k: opened.append(a) or ("", ""))
        p = _plugin(monkeypatch)
        page, center = _page(p)
        page._on_export()
        assert center.warnings, "没有记录就该明确说，而不是导出一个空文件"
        assert center.infos == []
        assert opened == [], "没有记录就不该弹保存框"

    def test_export_writes_the_audit_file(self, monkeypatch, tmp_path):
        from presentation import control_center as cc

        p = _plugin(monkeypatch)
        p.record_decision(_advice(), ACTION_ADOPT,
                          outcome={"focus_started": True, "focus_minutes": 45})
        target = tmp_path / "证据链.txt"
        monkeypatch.setattr(cc.QFileDialog, "getSaveFileName",
                            lambda *a, **k: (str(target), ""))
        page, center = _page(p)
        page._on_export()

        text = target.read_text(encoding="utf-8")
        assert "人机协同决策留痕" in text
        assert "上午的深度工作被切成 4 段" in text
        assert "推荐依据" in text
        assert center.infos and str(target) in center.infos[0][1]

    def test_cancelling_the_dialog_writes_nothing(self, monkeypatch, tmp_path):
        from presentation import control_center as cc

        p = _plugin(monkeypatch)
        p.record_decision(_advice(), ACTION_ADOPT)
        monkeypatch.setattr(cc.QFileDialog, "getSaveFileName",
                            lambda *a, **k: ("", ""))
        page, center = _page(p)
        page._on_export()
        assert list(tmp_path.iterdir()) == []
        assert center.infos == [] and center.warnings == []
