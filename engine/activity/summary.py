# -*- coding: utf-8 -*-
"""把活动分段聚合成「给模型看的」文本摘要（纯函数，可脱离 Qt 单测）。

为什么先在本地聚合，而不是把原始分段全丢给模型
    1. **隐私** —— 出网的是「应用 + 时长」的汇总，不是逐条明细。
       只取 top-N 应用，长尾的细枝末节根本不会离开本机。
    2. **成本** —— 一周的原始分段可能上千条，聚合成十几行后 token 少一个量级。
    3. **可测** —— 纯函数，输入分段输出文本，不碰网络。

注意这份文本是**给模型读的**，不是给用户看的：紧凑、无形容词。
给用户看的那份由 `dialog.py` 单独渲染。
"""
from __future__ import annotations

import time
from typing import Dict, Iterable, List, Optional

from .category import FOCUS_CATEGORIES, OTHER
from .timeline import switch_count

#: 摘要里最多列出几个应用 —— 超出部分合并成「其他 N 个应用」。
DEFAULT_TOP_APPS = 8


def human_duration(seconds: float) -> str:
    """把秒数写成人话："2 小时 10 分" / "45 分钟" / "30 秒"。"""
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{int(round(seconds))} 秒"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{int(round(minutes))} 分钟"
    hours = int(minutes // 60)
    rest = int(round(minutes - hours * 60))
    if rest == 60:
        hours, rest = hours + 1, 0
    return f"{hours} 小时 {rest} 分" if rest else f"{hours} 小时"


def _stamp(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))


def longest_focus_seconds(segments: Iterable[Dict]) -> float:
    """最长「连续专注」时长。

    连续 = 中间没有被「娱乐 / 沟通 / 其他」打断。在编辑器和浏览器之间来回
    切换查资料算作一整段专注，而不是两段。

    口径与 `timeline.focus_seconds` 同源（都走 `category.FOCUS_CATEGORIES`
    = 工作 + 学习）—— 两处各自写死 `"工作"` 的日子结束了：那样改一处
    就会让页面上的两个数字互相矛盾。
    """
    best = 0.0
    run = 0.0
    for seg in segments:
        if (seg.get("category") or "") in FOCUS_CATEGORIES:
            run += float(seg.get("seconds") or 0.0)
            best = max(best, run)
        else:
            run = 0.0
    return best


def build_summary(segments: List[Dict], *, top_apps: int = DEFAULT_TOP_APPS) -> str:
    """把分段聚合成一段给模型读的文本。空输入返回明确的「无记录」提示。"""
    segments = list(segments or [])
    if not segments:
        return "（本次没有采集到任何活动记录）"

    total = sum(float(s.get("seconds") or 0.0) for s in segments)
    if total <= 0:
        return "（采集到的记录时长都太短，不足以分析）"

    start = min(float(s.get("start_at") or 0.0) for s in segments)
    end = max(float(s.get("end_at") or 0.0) for s in segments)

    lines: List[str] = []
    lines.append(f"统计区间：{_stamp(start)} ~ {_stamp(end)}")
    lines.append(f"记录总时长：{human_duration(total)}")
    lines.append("")

    # --- 按应用 ---
    by_app: Dict[str, Dict] = {}
    for seg in segments:
        app = seg.get("app") or "unknown"
        item = by_app.setdefault(
            app, {"app": app, "category": seg.get("category") or OTHER,
                  "seconds": 0.0, "segments": 0}
        )
        item["seconds"] += float(seg.get("seconds") or 0.0)
        item["segments"] += 1
    ranked = sorted(by_app.values(), key=lambda x: x["seconds"], reverse=True)

    lines.append(f"按应用（前 {min(top_apps, len(ranked))} 个）：")
    for item in ranked[:top_apps]:
        share = item["seconds"] / total * 100 if total else 0.0
        lines.append(
            f"  {item['app']}（{item['category']}）"
            f" {human_duration(item['seconds'])}，占 {share:.0f}%，共 {item['segments']} 段"
        )
    if len(ranked) > top_apps:
        rest_seconds = sum(i["seconds"] for i in ranked[top_apps:])
        lines.append(f"  其余 {len(ranked) - top_apps} 个应用合计 {human_duration(rest_seconds)}")
    lines.append("")

    # --- 按类别 ---
    by_cat: Dict[str, float] = {}
    for seg in segments:
        cat = seg.get("category") or OTHER
        by_cat[cat] = by_cat.get(cat, 0.0) + float(seg.get("seconds") or 0.0)

    lines.append("按类别：")
    for cat, secs in sorted(by_cat.items(), key=lambda kv: kv[1], reverse=True):
        share = secs / total * 100 if total else 0.0
        lines.append(f"  {cat} {human_duration(secs)}（{share:.0f}%）")
    lines.append("")

    # --- 专注情况 ---
    lines.append("专注情况：")
    lines.append(f"  最长连续工作段：{human_duration(longest_focus_seconds(segments))}")
    # 这里原来写的是 `len(segments)`（段数）—— 段数 = 切换次数 + 1，
    # 而且多日数据里「昨天收尾 → 今天开工」还会被当成一次切换。
    # 模型据此数说「你今天切换了 47 次」，比事实多一次且不跨天。
    # 口径统一走 `timeline.switch_count`，与页面上那个数字同源。
    lines.append(f"  应用切换次数：{switch_count(segments)}")
    lines.append(f"  平均每段：{human_duration(total / len(segments))}")

    return "\n".join(lines)
