# -*- coding: utf-8 -*-
"""结构化建议 —— 把模型输出解析成「结论 / 证据 / 动作」三段（纯函数，零 Qt）。

为什么必须结构化
    纯文本建议有四个毛病：**不可扫读**（要读完整段才知道在说什么）、
    **不可执行**（说了「该专注」却没有按钮）、**不可忽略**（没有出口）、
    **不可追溯**（结论和证据混在一起，用户没法核对 AI 凭什么这么说）。
    拆成三段之后，UI 才能把「一段话」变成「一张可操作的卡片」。

为什么动作必须是**受限枚举**，不能让模型自由发挥
    模型很容易写出「打开番茄钟设置页把时长改成 45 分钟」这种 UI 根本
    执行不了的指令。所以动作只允许两种：`focus`（带分钟数）和 `none`，
    而且分钟数会被夹到 `ALLOWED_FOCUS_MINUTES` 里最近的一个 ——
    **模型说什么都不会让程序做出意外的事**。这是安全边界，不是偷懒。

为什么用 JSON 而不是「约定文本格式」
    「结论 / 证据 / 动作」是精确结构，文本格式要靠正则猜，模型一换行就崩。
    JSON 有明确的解析边界，而且解析失败还能**降级**（见 `parse_advices`）——
    UI 永远有东西可显示，不会因为模型不听话就白屏。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

#: 动作类型 —— 受限枚举，模型不能发明新的。
ACTION_FOCUS = "focus"
ACTION_NONE = "none"

#: 允许的专注时长（分钟）。模型给的其它值会被夹到最近的一个。
ALLOWED_FOCUS_MINUTES: Tuple[int, ...] = (25, 45, 90)

#: 单条建议最多保留几条证据 —— 多了卡片会高得没法扫读。
MAX_EVIDENCE = 3

#: 一次最多展示几条建议。
MAX_ADVICES = 4

#: 总结最多保留多少字。
#: 总结是**一眼看结论**的那一行，长了会把下面的建议卡挤出首屏，
#: 也就失去了「先看结论、再看依据」的意义。
MAX_SUMMARY_CHARS = 120


@dataclass(frozen=True)
class AdviceAction:
    """建议的动作。`kind` 只可能是 `focus` / `none`。"""

    kind: str = ACTION_NONE
    minutes: int = 0
    label: str = ""

    @property
    def is_actionable(self) -> bool:
        """能不能变成一个真的按钮。"""
        return self.kind == ACTION_FOCUS and self.minutes > 0


@dataclass(frozen=True)
class Advice:
    """一条建议 = 结论 + 证据 + 动作。"""

    headline: str
    evidence: Tuple[str, ...] = ()
    action: AdviceAction = AdviceAction()

    @property
    def fingerprint(self) -> str:
        """忽略状态的键（见 `advice_fingerprint`）。"""
        return advice_fingerprint(self.headline)


@dataclass(frozen=True)
class AdviceReport:
    """一次生成的完整结果 = **一段总结** + 若干条建议。

    为什么总结由模型给，而不是本地拼模板句
        本地能拼出来的只有「今天 6 小时，深度工作 2 小时」这种数字复述 ——
        那和上面的指标卡是同一份信息，再写一遍等于占地方。
        真正有用的是**数字之间的关系**（「下午被切得很碎」），
        那需要读懂摘要，正是模型该干的活。所以总结进 JSON，和证据一样
        受「只能用摘要里出现过的数字」这条约束管。

    为什么 `advices` 是元组
        frozen dataclass + 元组 = 解析结果不可被下游就地改坏。
        页面只读它，不该有能力改。
    """

    summary: str = ""
    advices: Tuple[Advice, ...] = ()

    @property
    def has_summary(self) -> bool:
        return bool(self.summary)

    def __bool__(self) -> bool:
        """空报告（没有总结、也没有建议）为假 —— 页面据此判断「有没有东西可画」。"""
        return bool(self.summary) or bool(self.advices)


def _normalize(text: str) -> str:
    """归一化：去掉空白、标点和**数字**，用来生成稳定的指纹。

    为什么要去掉数字
        同一类建议，模型每次给的统计值都会有出入（「打断 9 次」/「打断 8 次」）。
        精确匹配会让「忽略」形同虚设 —— 用户刚点完忽略，下次生成又冒出来。
        去掉数字后这两种会归到同一个指纹。

    为什么去掉数字是安全的
        时段、应用名、动作这些**语义**信息都是文字，不会被去掉：
        「上午被打断 9 次」和「下午被打断 9 次」归一化后仍是两个不同的串。
        被合并的只有「同一件事、数值不同」这种情况，那正是我们想要的。
    """
    return re.sub(
        r"[\d\s，。、：；！？,.:;!?\-—–()（）「」『』\"'`·|%]+", "", str(text or "")
    )


def advice_fingerprint(headline: str) -> str:
    """建议指纹：归一化结论文本的 sha1 前 16 位。"""
    return hashlib.sha1(_normalize(headline).encode("utf-8")).hexdigest()[:16]


def _clamp_minutes(value: Any) -> int:
    """把模型给的分钟数夹到允许集合里最近的一个。非法值返回 0。"""
    try:
        minutes = int(float(value))
    except (TypeError, ValueError):
        return 0
    if minutes <= 0:
        return 0
    return min(ALLOWED_FOCUS_MINUTES, key=lambda m: abs(m - minutes))


def _parse_action(raw: Any) -> AdviceAction:
    if not isinstance(raw, dict):
        return AdviceAction()
    kind = str(raw.get("kind") or "").strip().lower()
    if kind != ACTION_FOCUS:
        return AdviceAction()
    minutes = _clamp_minutes(raw.get("minutes"))
    if minutes <= 0:
        return AdviceAction()
    return AdviceAction(
        kind=ACTION_FOCUS, minutes=minutes, label=f"开始 {minutes} 分钟专注"
    )


def _parse_one(raw: Any) -> Optional[Advice]:
    if not isinstance(raw, dict):
        return None
    headline = str(raw.get("headline") or "").strip()
    if not headline:
        return None
    ev_raw = raw.get("evidence") or []
    if isinstance(ev_raw, str):
        ev_raw = [ev_raw]
    evidence = tuple(
        str(e).strip() for e in ev_raw if str(e or "").strip()
    )[:MAX_EVIDENCE]
    return Advice(
        headline=headline, evidence=evidence, action=_parse_action(raw.get("action"))
    )


def _extract_json(text: str) -> Optional[Any]:
    """从模型输出里抠出 JSON。

    模型常见的不听话：包了 ```json 代码块、前面加一句「好的，这是建议：」。
    所以依次尝试：直接解析 → 去围栏后解析 → 取最外层数组 → 取最外层对象。
    """
    s = str(text or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        pass

    s2 = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s2 = re.sub(r"\s*```$", "", s2).strip()
    try:
        return json.loads(s2)
    except (ValueError, TypeError):
        pass

    for open_ch, close_ch in _bracket_order(s2):
        start, end = s2.find(open_ch), s2.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(s2[start:end + 1])
            except (ValueError, TypeError):
                continue
    return None


def _bracket_order(text: str) -> List[Tuple[str, str]]:
    """按「哪个括号先出现」决定先试对象还是先试数组。

    为什么不能固定先试数组
        新格式是 `{"summary": …, "advices": [ … ]}` —— 对象**里面**嵌着数组。
        固定先试 `[` 会抠出内层数组并**解析成功**，于是 summary 被静默丢掉。
        这种「错误地成功」比解析失败难查得多：界面上只是总结没了，
        看不出是解析的问题。

        旧格式（裸数组）里 `[` 在 `{` 前面，所以这个顺序对两种格式都对。
    """
    order = [("[", "]"), ("{", "}")]
    return sorted(order, key=lambda pair: (
        text.find(pair[0]) if text.find(pair[0]) != -1 else len(text)
    ))


def is_structured(text: str) -> bool:
    """文本里是否有**真正可解析的** JSON 结构。

    为什么需要这个判据
        `parse_advices` 的契约是「**永不返回空**」—— 解析不出来时会降级成
        一条兜底建议。但 UI 需要知道这是「模型真的按格式给了结构」
        还是「模型回了一段大白话」：前者画成建议卡，后者应当**原样显示**，
        否则会把一段散文硬塞进「结论 / 证据 / 动作」的壳里，读起来很怪。

    流式输出时会一直返回 False —— 半截的 `[{"headline": "…` 解析不出来，
    于是页面不会闪一堆残缺的卡片（见 TodayPage._render_advice）。
    """
    return _extract_json(text) is not None


def _clamp_summary(text: Any) -> str:
    """把模型给的总结压成一行：折叠所有空白 + 截断。

    换行必须折掉 —— 总结要在卡片上方占**一行**，模型写成多段会把它撑成
    半个屏幕，比没有总结还糟。
    """
    return " ".join(str(text or "").split())[:MAX_SUMMARY_CHARS]


def parse_report(text: str) -> AdviceReport:
    """把模型输出解析成「总结 + 建议」。**永不抛异常**。

    三种输入都要能处理（第 ② 种是 P2.18 之前写进缓存的格式，
    用户升级后第一次打开页面读到的就是它）：

      ① 新格式：`{"summary": "…", "advices": [ … ]}`
      ② 旧格式：`[ {…}, {…} ]` —— 没有总结，`summary` 为空串（页面就不画总结块）
      ③ 大白话：整段当结论，首行做 headline（与旧的降级行为一致）

    降级为什么只做一层
        ①②都能给出「结构化建议」，差别只在有没有总结；③ 连结构都没有，
        页面会走「原样显示」那条路（`is_structured()` 为 False），
        此时硬塞一段总结反而会和大白话正文重复。
    """
    raw = str(text or "").strip()
    if not raw:
        return AdviceReport()

    data = _extract_json(raw)
    summary = ""
    structured = data is not None
    if isinstance(data, dict):
        summary = _clamp_summary(data.get("summary"))
        # 用 `in` 而不是 `or` 链：模型按格式说明给出
        # `{"summary": "…", "advices": []}`（数据不足时的标准答案）时，
        # 空数组是**有效内容**而不是「字段缺失」—— `or` 会把它当缺失，
        # 退回 `[data]`，于是总结被丢掉、页面还把整段 JSON 当大白话显示。
        if "advices" in data:
            data = data.get("advices")
        elif "items" in data:
            data = data.get("items")
        else:
            data = [data]

    items: List[Advice] = []
    if isinstance(data, list):
        for entry in data:
            adv = _parse_one(entry)
            if adv is not None:
                items.append(adv)
    if items or summary:
        return AdviceReport(summary=summary, advices=tuple(items[:MAX_ADVICES]))
    if structured:
        # 是合法 JSON、但没有可用的建议与总结（例如模型回了 `[]`）。
        # **不能**退回大白话降级 —— 那会把 `[]` 当成一条「结论」显示出来。
        return AdviceReport()

    # ③ 大白话降级 —— 没有结构，也就没有总结
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    headline = (lines[0] if lines else raw)[:120]
    evidence = tuple(ln[:120] for ln in lines[1:1 + MAX_EVIDENCE])
    return AdviceReport(advices=(Advice(headline=headline, evidence=evidence),))


def parse_advices(text: str) -> List[Advice]:
    """把模型输出解析成结构化建议列表（`parse_report` 的只取建议版）。

    解析不出来时降级成「一条没有证据的建议」，headline 取原文首行 ——
    宁可展示得不完美，也不能让页面空着（用户会以为功能坏了）。
    """
    return list(parse_report(text).advices)


def advice_to_text(advices: List[Advice]) -> str:
    """把结构化建议还原成人读的文本 —— 用于日志、或兼容旧的纯文本视图。"""
    out: List[str] = []
    for i, adv in enumerate(advices, 1):
        out.append(f"{i}. {adv.headline}")
        for e in adv.evidence:
            out.append(f"   · {e}")
        if adv.action.is_actionable:
            out.append(f"   → {adv.action.label}")
    return "\n".join(out)


#: 给模型的输出格式说明。放进 system prompt 与提问里各一份（双重保险）。
ADVICE_JSON_SPEC = (
    "只输出一个 JSON 对象，**不要**任何解释文字、不要 markdown 代码块。格式：\n"
    "{\n"
    '  "summary": "一段整体总结（不超过 60 字）：今天的时间主要花在哪、'
    '节奏怎么样。**不要**重复下面单条建议的内容",\n'
    '  "advices": [\n'
    '    {"headline": "一句话结论（不超过 30 字）",\n'
    '     "evidence": ["支撑它的具体数据（1-3 条，每条不超过 40 字）"],\n'
    '     "action": {"kind": "focus", "minutes": 45}}\n'
    "  ]\n"
    "}\n"
    "\n"
    "action 只能取两种之一：\n"
    '  {"kind": "focus", "minutes": 25}  —— 25 / 45 / 90 三个值，'
    "当这条建议适合用一个专注时段来改善时使用\n"
    '  {"kind": "none"}                  —— 当这条建议不适合用专注时段解决时使用\n'
    "\n"
    "最多 3 条建议。headline 要像「上午的深度工作被切成 4 段」这样具体，"
    "不要写「要提高效率」这种空话。summary 要像「今天 6 小时里深度工作只占 "
    "2 小时，下午被切得比较碎」这样一眼能读懂今天的状态。"
)
