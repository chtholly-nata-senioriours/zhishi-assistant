# -*- coding: utf-8 -*-
"""「总结 + 建议」解析（P2.18）的回归测试。

守三件事：
    · **新格式**：`{"summary": …, "advices": [ … ]}` 能同时拿到总结与建议。
    · **旧格式不炸**：P2.18 之前写进缓存的裸数组升级后照样能读 ——
      否则用户升级完第一次打开「今日」页会看到一片空白。
    · **解析永不抛**：模型给什么（半截 JSON、大白话、`None`）都得有东西可显示。

运行:
    python dev_bootstrap.py -m pytest tests/test_advice_report.py -q
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.activity import (  # noqa: E402
    ADVICE_JSON_SPEC,
    MAX_ADVICES,
    MAX_SUMMARY_CHARS,
    Advice,
    AdviceReport,
    build_advisor_prompt,
    parse_advices,
    parse_report,
)

#: 新格式的一次完整输出。
_NEW_FORMAT = (
    '{"summary": "今天 6 小时里深度工作只占 2 小时，下午被切得比较碎",'
    ' "advices": ['
    '  {"headline": "上午的深度工作被切成 4 段",'
    '   "evidence": ["9:00-11:00 共切换 4 次"],'
    '   "action": {"kind": "focus", "minutes": 45}},'
    '  {"headline": "下午的会议占了两小时",'
    '   "evidence": ["会议类应用停留 118 分钟"],'
    '   "action": {"kind": "none"}}'
    "]}"
)

#: P2.18 之前写进缓存的格式（裸数组）。
_LEGACY_FORMAT = (
    '[{"headline": "上午被切成 4 段", "evidence": ["切换 4 次"],'
    '  "action": {"kind": "focus", "minutes": 25}}]'
)


# ================================================================
# 1. 新格式
# ================================================================

def test_parse_report_reads_summary_and_advices():
    report = parse_report(_NEW_FORMAT)
    assert report.summary == "今天 6 小时里深度工作只占 2 小时，下午被切得比较碎"
    assert len(report.advices) == 2
    assert report.advices[0].headline == "上午的深度工作被切成 4 段"
    assert report.advices[0].action.minutes == 45
    assert report.advices[1].action.is_actionable is False


def test_report_is_truthy_only_when_it_has_content():
    """空报告必须为假 —— 页面靠它判断「有没有东西可画」。"""
    assert bool(AdviceReport()) is False
    assert bool(parse_report("")) is False
    assert bool(parse_report(_NEW_FORMAT)) is True
    # 只有总结、没有建议（模型把 advices 给了空数组）也算有内容
    assert bool(parse_report('{"summary": "今天还行", "advices": []}')) is True


def test_empty_advices_do_not_swallow_the_summary():
    """`{"summary": "…", "advices": []}` 是**合法结果**，不是解析失败。

    这是格式说明里明确要求的一种回答（数据不足时给空数组），
    所以「空数组」必须被当成**内容**而不是「字段缺失」。

    反向验证发现这条断言的第一版是**假**的：它只钉住了「`in` 判断」，
    而真正兜住总结的是返回值那一句 `if items or summary:` ——
    把 `in` 改回 `or` 链，总结照样在（`_parse_one` 对没有 headline 的
    dict 返回 None，于是走不到「造一条假建议」那条路）。
    所以真正要钉的是那个 `or summary`。
    """
    report = parse_report('{"summary": "今天只有零星记录", "advices": []}')
    assert report.summary == "今天只有零星记录"
    assert report.advices == ()
    assert report.has_summary is True


def test_an_empty_json_result_is_not_turned_into_a_fake_advice():
    """模型回 `[]` 时不许造一条内容是 `[]` 的「建议」出来。"""
    for text in ("[]", "{}", '{"advices": []}'):
        report = parse_report(text)
        assert report.advices == (), text
        assert report.summary == "", text
        assert bool(report) is False, text


# ================================================================
# 2. 旧格式与降级
# ================================================================

def test_parse_report_accepts_the_legacy_bare_array():
    """旧缓存是裸数组 —— 升级后第一次打开页面读到的就是它。

    没有总结是**正常**的（那时模型还没被要求写），不能因此判成解析失败。
    """
    report = parse_report(_LEGACY_FORMAT)
    assert report.summary == ""
    assert report.has_summary is False
    assert len(report.advices) == 1
    assert report.advices[0].headline == "上午被切成 4 段"


def test_parse_report_does_not_lose_the_summary_behind_prose():
    """模型爱在 JSON 前面加一句「好的，这是建议：」—— 总结不能被吃掉。

    这是最容易写错、也最难发现的一条：`{"summary": …, "advices": [ … ]}`
    里**嵌着**数组。抠 JSON 时若固定先试 `[...]`，会抠出内层数组并
    「解析成功」，于是总结被静默丢掉 —— 界面上只是总结没了，
    看不出是解析的问题。
    """
    text = "好的，这是今天的建议：\n" + _NEW_FORMAT + "\n希望对你有帮助。"
    report = parse_report(text)
    assert report.summary.startswith("今天 6 小时里")
    assert len(report.advices) == 2

    fenced = "```json\n" + _NEW_FORMAT + "\n```"
    assert parse_report(fenced).summary.startswith("今天 6 小时里")


def test_parse_report_folds_the_summary_into_one_line():
    """总结要在卡片上方占**一行**：换行折掉、超长截断。

    模型写成多段会把它撑成半个屏幕，比没有总结还糟。
    """
    report = parse_report(
        '{"summary": "第一行\\n\\n  第二行   还有   很多空格", "advices": []}'
    )
    assert "\n" not in report.summary
    assert "  " not in report.summary
    assert report.summary == "第一行 第二行 还有 很多空格"

    long_summary = "很" * (MAX_SUMMARY_CHARS + 80)
    got = parse_report(f'{{"summary": "{long_summary}", "advices": []}}')
    assert len(got.summary) == MAX_SUMMARY_CHARS


def test_parse_report_falls_back_to_plain_text():
    """大白话降级：整段当结论、首行做 headline，**但不编一段总结**。

    这时页面走「原样显示」那条路，硬塞总结只会和大白话正文重复。
    """
    report = parse_report("今天挺忙的\n上午写代码\n下午开会")
    assert report.summary == ""
    assert len(report.advices) == 1
    assert report.advices[0].headline == "今天挺忙的"
    assert report.advices[0].evidence == ("上午写代码", "下午开会")


def test_parse_report_never_raises_on_garbage():
    """模型给什么都不能把页面打崩 —— 这是 `parse_*` 的硬契约。"""
    for bad in (None, "", "   ", "{", "[", "{{{{", "null", "12345",
                '{"summary": null, "advices": null}',
                '{"summary": 42, "advices": "不是数组"}',
                '{"advices": [null, 7, {"没有headline": 1}]}'):
        report = parse_report(bad)
        assert isinstance(report, AdviceReport)
        assert isinstance(report.summary, str)
        for adv in report.advices:
            assert isinstance(adv, Advice)
            assert adv.headline


def test_parse_report_caps_the_number_of_advices():
    items = ",".join(f'{{"headline": "第 {i} 条"}}' for i in range(9))
    report = parse_report('{"summary": "s", "advices": [' + items + "]}")
    assert len(report.advices) == MAX_ADVICES


# ================================================================
# 3. 与旧 API 的一致性
# ================================================================

def test_parse_advices_still_returns_the_same_list():
    """`parse_advices` 是 `parse_report` 的只取建议版 —— 两者不能各算各的。"""
    for text in (_NEW_FORMAT, _LEGACY_FORMAT, "大白话一行", "", "{{{"):
        assert parse_advices(text) == list(parse_report(text).advices)


# ================================================================
# 4. 提示词必须**要**总结
# ================================================================

def test_spec_asks_for_a_summary_field():
    """只在解析端支持总结是不够的 —— 不向模型要，它就永远不给。

    这条钉的是「格式说明里必须出现 summary」，而且必须出现在
    **要求输出 JSON 的那段**里（system prompt 与提问各带一份，见 advisor.py）。
    """
    assert '"summary"' in ADVICE_JSON_SPEC
    assert "advices" in ADVICE_JSON_SPEC


def test_advisor_prompt_asks_for_a_summary():
    prompt = build_advisor_prompt("统计区间：x\n记录总时长：1 小时", days=1)
    assert '"summary"' in prompt
    assert "summary" in prompt


def test_system_prompt_keeps_the_no_guessing_rules():
    """新加的总结不能把原有的两条硬约束挤掉（防臆测 / 证据必须真实）。

    总结同样受这两条管 —— 它是模型唯一被允许「下判断」的地方，
    正是最容易开始编内容的位置。

    反向验证发现「只断言出现 `summary` 这个词」是**假**的：
    把规则 7 改成「**先给建议数组**」它照样绿（后半句还带着 summary 三个字）。
    所以要钉的是**那句指令**，不是一个词。
    """
    from engine.activity import ADVISOR_SYSTEM_PROMPT

    assert "不要臆测" in ADVISOR_SYSTEM_PROMPT
    assert "证据" in ADVISOR_SYSTEM_PROMPT
    assert "先给一段 summary" in ADVISOR_SYSTEM_PROMPT, (
        "规则里没有「先给总结」这条指令 —— 只在格式说明里要是不够的，"
        "system prompt 才是模型真正当命令读的地方"
    )
