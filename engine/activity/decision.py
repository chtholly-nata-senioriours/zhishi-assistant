# -*- coding: utf-8 -*-
"""人机协同决策留痕 —— 把「用户拿这条建议怎么办」变成可审计的证据链。

为什么需要它
    「一键采纳 / 忽略」以前只落一个指纹（`ignored_advices` 表）。那只回答
    「这条建议别再出现」，回答不了三个更值钱的问题：
        ① 用户当时**凭什么**同意 / 否决（依据会被下一次生成覆盖）；
        ② 那一刻**数据是什么样**（同一句结论，6 小时和 2 小时含义完全不同）；
        ③ 这个动作**影响了什么**（是开始了 45 分钟专注，还是只是不再出现）。
    「可解释的人机协同」要的正是这三样。所以存的不是又一份结论，
    而是**做决定时的现场**。

三条设计纪律
    1. **现场在动作那一刻固化**，不事后补。建议会重新生成、数据会变化，
       只有当场快照能证明「他当时看到的就是这个」。
    2. **上下文只放聚合数字**（条数 / 总时长 / 起止 / 是否过期）。窗口标题、
       按键、剪贴板这些**从来就不采集**的字段，不能从留痕这条路径绕进来 ——
       与 `activity.db` 没有 title 列是同一条边界，做法也一样：
       `_clean_context` 用**白名单**，认不出的键直接丢掉。
    3. **纯函数 + frozen dataclass**：生成留痕这件事能被单测覆盖，
       不必起一个窗口、也不必真的连上 AI。

与 `advice.py` 的分工
    `advice.py` 管「模型说了什么」，本模块管「人对此做了什么」。
    前者是输入，后者是决策；中间隔着一次人的判断，两边都不该越界。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

#: 用户能做的两种决定。**受限枚举**，和 `advice.ACTION_*` 同一思路：
#: 界面只有两个按钮，库里就不该出现第三种取值。
ACTION_ADOPT = "adopt"
ACTION_IGNORE = "ignore"
ACTIONS: Tuple[str, ...] = (ACTION_ADOPT, ACTION_IGNORE)

#: 决定类型的中文标签（界面上不出现裸英文）。
ACTION_LABELS = {ACTION_ADOPT: "采纳", ACTION_IGNORE: "忽略"}

#: 上下文快照里允许出现的键。**白名单** —— 见纪律 2。
CONTEXT_KEYS: Tuple[str, ...] = (
    "scope",        # 数据范围的中文名（今日 / 近 7 天）
    "days",         # 折算成几天（机器可读）
    "segments",     # 现场有多少段记录
    "tracked_seconds",  # 现场累计记录时长
    "range",        # [起, 止]（epoch 秒，展示层再格式化）
    "summary",      # 同一批建议自带的那段总结
    "advice_created_at",  # 这条建议是什么时候生成的
    "advice_stale",  # 生成之后数据又变了没有
    "focus_running",  # 做决定时专注计时在不在跑
    "generated_by",  # 建议由哪个功能产出
)

#: 总结在留痕里也夹一下 —— 它来自模型，长度不受我们控制。
MAX_CONTEXT_SUMMARY = 120


@dataclass(frozen=True)
class DecisionNote:
    """一次决定的完整留痕。

    三个字段对应三个问题：`basis` 答「凭什么」，`context` 答「当时是什么
    情况」，`impact` 答「影响了什么」。`fingerprint` / `headline` 是定位用，
    没有它们，「这条建议」在留痕里就指向不明。
    """

    fingerprint: str
    headline: str
    action: str
    at: float
    basis: Tuple[str, ...] = ()
    context: Dict[str, Any] = field(default_factory=dict)
    impact: str = ""

    # ----- 序列化（落库 / 导出用；不动内部结构，于是以后加字段不破坏旧数据）-----

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "headline": self.headline,
            "action": self.action,
            "at": self.at,
            "basis": list(self.basis),
            "context": dict(self.context),
            "impact": self.impact,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> Optional["DecisionNote"]:
        """从落库的 JSON 还原。**格式不对就返回 None**，不让半条数据流到界面上。"""
        if not isinstance(raw, dict):
            return None
        action = str(raw.get("action") or "")
        if action not in ACTIONS:
            return None
        basis = raw.get("basis")
        basis = tuple(str(b) for b in basis) if isinstance(basis, (list, tuple)) else ()
        context = raw.get("context")
        if not isinstance(context, dict):
            context = {}
        try:
            at = float(raw.get("at") or 0.0)
        except (TypeError, ValueError):
            at = 0.0
        return cls(
            fingerprint=str(raw.get("fingerprint") or ""),
            headline=str(raw.get("headline") or ""),
            action=action,
            at=at,
            basis=basis,
            context=context,
            impact=str(raw.get("impact") or ""),
        )

    @property
    def action_label(self) -> str:
        return ACTION_LABELS.get(self.action, self.action)

    def describe(self) -> str:
        """单行摘要（表格里放得下的那种）。"""
        stamp = time.strftime("%m-%d %H:%M", time.localtime(self.at)) if self.at else "—"
        return f"[{stamp}] {self.action_label}：{self.headline}"


# ------------------------------------------------------------ 现场


def build_context(days: int, segments: Optional[List[dict]], *,
                  summary: str = "", advice_created_at: float = 0.0,
                  advice_stale: bool = False, focus_running: bool = False,
                  generated_by: str = "") -> Dict[str, Any]:
    """把「决定那一刻的数据现场」收成一个**只含聚合数字**的字典。

    `segments` 只用来数条数和算总时长 / 起止 —— 不取任何一段的 app 名。
    为什么连 app 名都不放：留痕要回答的是「当时数据量够不够、结论站不站得住」，
    那个问题用数字就能答；放上 app 名只是多一份可以顺藤摸瓜的隐私。
    """
    items = list(segments or [])
    total = 0.0
    start = end = 0.0
    for s in items:
        try:
            total += float(s.get("seconds") or 0.0)
            st = float(s.get("start_at") or 0.0)
            en = float(s.get("end_at") or 0.0)
        except (AttributeError, TypeError, ValueError):
            continue
        start = st if not start else min(start, st)
        end = max(end, en)
    ctx: Dict[str, Any] = {
        "scope": "今日" if int(days) <= 1 else f"近 {int(days)} 天",
        "days": int(days),
        "segments": len(items),
        "tracked_seconds": int(total),
    }
    if start and end:
        ctx["range"] = [start, end]
    summary = str(summary or "").strip()
    if summary:
        ctx["summary"] = summary[:MAX_CONTEXT_SUMMARY]
    if advice_created_at:
        ctx["advice_created_at"] = float(advice_created_at)
    # 两个布尔**总是记**（含 False）：留痕要能区分「当时没在专注」与
    # 「当时没检查」—— 只记 True 的话，读的人分不出这两种。
    ctx["advice_stale"] = bool(advice_stale)
    ctx["focus_running"] = bool(focus_running)
    if generated_by:
        ctx["generated_by"] = str(generated_by)
    return _clean_context(ctx)


def _clean_context(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """白名单过滤 —— 认不出的键**直接丢掉**，原样留着会有路径把用户内容带进留痕。

    与 `activity.db` 的「没有 title 列」是同一种结构性保证：
    不靠「调用方记得别放」，靠「这里就收不进去」。

    只丢「空」值（None / 空串 / 空容器）；**`0` 与 `False` 要留下** ——
    「现场 0 段记录」「生成后数据未变化」都是要如实记下来的事实，
    被当成空值丢掉，留痕就变成了「没检查」。
    """
    src = raw or {}
    out: Dict[str, Any] = {}
    for key in CONTEXT_KEYS:
        if key not in src:
            continue
        value = src[key]
        if value is None or value == "" or value == [] or value == {}:
            continue
        out[key] = value
    return out


# ------------------------------------------------------------ 留痕


def build_note(advice, action: str, *, summary: str = "",
               context: Optional[Dict[str, Any]] = None,
               outcome: Optional[Dict[str, Any]] = None,
               now: Optional[float] = None) -> DecisionNote:
    """为一次决定生成留痕。

    Args:
        advice: `engine.activity.advice.Advice`（鸭子类型，只要有
                `fingerprint` / `headline` / `evidence` / `action`）
        action: `adopt` / `ignore`
        summary: 这批建议自带的总结（进上下文，不进依据）
        context: `build_context()` 的产物；也可以直接给 dict，会过白名单
        outcome: 采纳的**实际结果**（`focus_started` / `focus_minutes`）。
                 不带就按「没开始」处理 —— 宁可记成没开始，也不能谎称开始了。

    Returns:
        DecisionNote（不可变）

    Raises:
        ValueError: action 不在枚举里，或 advice 缺字段
    """
    if action not in ACTIONS:
        raise ValueError(f"未知的决定类型: {action!r}（只允许 {ACTIONS}）")
    fingerprint = str(getattr(advice, "fingerprint", "") or "")
    headline = str(getattr(advice, "headline", "") or "")
    if not fingerprint or not headline:
        raise ValueError("建议缺少 fingerprint / headline，无法定位这条留痕")

    ctx = _clean_context(context)
    summary = str(summary or "").strip()
    if summary and "summary" not in ctx:
        ctx["summary"] = summary[:MAX_CONTEXT_SUMMARY]

    return DecisionNote(
        fingerprint=fingerprint,
        headline=headline,
        action=action,
        at=time.time() if now is None else float(now),
        basis=_build_basis(advice),
        context=ctx,
        impact=_build_impact(action, advice, outcome),
    )


def _build_basis(advice) -> Tuple[str, ...]:
    """推荐依据 = 模型给的证据；采纳时再把「要做的动作」也算一条。

    为什么采纳要把动作写进依据
        「开始 45 分钟专注」是用户同意的**具体内容**。只写证据不写动作，
        留痕就说不清他到底同意了什么 —— 45 和 25 是两回事。
    """
    items: List[str] = []
    for e in (getattr(advice, "evidence", ()) or ()):
        text = str(e or "").strip()
        if text:
            items.append(text)
    action = getattr(advice, "action", None)
    if action is not None and getattr(action, "is_actionable", False):
        label = str(getattr(action, "label", "") or "").strip()
        if label:
            items.append(f"动作：{label}")
    return tuple(items)


def _build_impact(action: str, advice, outcome: Optional[Dict[str, Any]]) -> str:
    """影响范围 —— 一句话说清这个动作改变了什么、没改变什么。

    「没改变什么」不是客套：忽略一条建议**不影响本机记录**，
    这句话能拦住「我以为点忽略会删数据」的误解。
    """
    if action == ACTION_IGNORE:
        return ("该建议及其同类（同指纹）不再出现在后续推荐中；"
                "不影响本机活动记录，也不影响其他建议。")

    result = outcome or {}
    started = bool(result.get("focus_started"))
    minutes = int(result.get("focus_minutes") or 0)
    action_obj = getattr(advice, "action", None)
    if not minutes and action_obj is not None and getattr(action_obj, "is_actionable", False):
        minutes = int(getattr(action_obj, "minutes") or 0)
    if started and minutes:
        return (f"已开始 {minutes} 分钟专注时段；"
                "该建议标记为已采纳，仍留在列表中（按钮转为进行态）。")
    if started:
        return "已开始一个专注时段；该建议标记为已采纳，仍留在列表中。"
    return ("未开始专注（计时已在跑，或番茄钟插件未加载）；"
            "仅记录本次采纳，不做其他改动。")


# ------------------------------------------------------------ 导出


def format_notes(notes: List[DecisionNote]) -> str:
    """把留痕导出成一份**人可直接读**的审计文本（UTF-8）。

    为什么导出成文本而不是只让用户在界面里翻
        界面是给「看一眼」的，审计是给「逐条核对」的。后者要能 diff、
        能存档、能贴进报告 —— 这些都要求一份稳定的纯文本。
    """
    items = [n for n in (notes or []) if isinstance(n, DecisionNote)]
    adopted = sum(1 for n in items if n.action == ACTION_ADOPT)
    ignored = sum(1 for n in items if n.action == ACTION_IGNORE)
    lines: List[str] = [
        "人机协同决策留痕（知时助手）",
        f"共 {len(items)} 条决定（采纳 {adopted} / 忽略 {ignored}）",
        "说明：每条记录包含推荐依据、决定时的数据现场与影响范围。",
        "=" * 64,
    ]
    for note in sorted(items, key=lambda n: n.at, reverse=True):
        stamp = (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(note.at))
                 if note.at else "（时间未知）")
        lines.append(f"[{stamp}] {note.action_label}")
        lines.append(f"结论：{note.headline}")
        if note.basis:
            lines.append("推荐依据：")
            lines.extend(f"  · {b}" for b in note.basis)
        else:
            lines.append("推荐依据：（模型未提供证据）")
        lines.append(f"上下文：{format_context(note.context)}")
        lines.append(f"影响范围：{note.impact or '（未记录）'}")
        lines.append("-" * 64)
    return "\n".join(lines) + "\n"


def format_context(ctx: Dict[str, Any]) -> str:
    """上下文字典 → 一行中文。展示层直接用，别再自己拼一遍。"""
    if not ctx:
        return "（未记录）"
    parts: List[str] = []
    if ctx.get("scope"):
        parts.append(str(ctx["scope"]))
    if "segments" in ctx:
        parts.append(f"现场 {ctx['segments']} 段记录")
    if "tracked_seconds" in ctx:
        from .summary import human_duration

        parts.append(f"累计 {human_duration(float(ctx['tracked_seconds']))}")
    if ctx.get("range"):
        start, end = ctx["range"][0], ctx["range"][-1]
        span = (time.strftime("%H:%M", time.localtime(float(start)))
                + "–" + time.strftime("%H:%M", time.localtime(float(end))))
        parts.append(f"数据范围 {span}")
    if ctx.get("summary"):
        parts.append(f"当时的总结「{ctx['summary']}」")
    if ctx.get("advice_created_at"):
        parts.append("建议生成于 "
                     + time.strftime("%H:%M", time.localtime(float(ctx["advice_created_at"]))))
    parts.append("生成后数据已变化" if ctx.get("advice_stale") else "生成后数据未变化")
    parts.append("决定时专注正在进行" if ctx.get("focus_running") else "决定时专注未在进行")
    if ctx.get("generated_by"):
        parts.append(f"来源 {ctx['generated_by']}")
    return "；".join(parts)
