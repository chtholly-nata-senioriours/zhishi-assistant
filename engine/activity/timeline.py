# -*- coding: utf-8 -*-
"""时间轴与趋势的聚合（纯函数，零 Qt 依赖）。

为什么单独一个模块
    这里放的都是「把 segments 变成图形能直接用的形状」的纯函数 ——
    合并碎片段、按自然日聚合、取排行。它们既服务于「今日」页的 24 小时
    时间轴，也服务于「趋势」页的柱状图。放一起才不会两处各写一份，
    也才不会两处口径不一致（比如两个页面给出不同的「深度工作」时长）。

为什么合并逻辑必须可单测
    P2.13 加了空闲剪裁之后，一天可能产生几十个小段。合并规则一旦写错，
    时间轴会**静默地**画错（少算或多算时间），肉眼根本看不出来。
    所以合并放数据层，用测试钉死，不放进渲染代码。
"""
from __future__ import annotations

import time
from typing import Dict, Iterable, List, Optional

from .category import FOCUS_CATEGORIES, OTHER, WORK
from .schedule import DAY_SECONDS, day_start

#: 判定「工作」的类别名。保留这个名字是为了兼容既有引用；
#: 真正的口径是 `FOCUS_CATEGORIES`（工作 + 学习）—— 见下。
WORK_CATEGORY = WORK

#: 合并碎片段的默认间隔阈值（秒）。
#: 「切走看一眼消息又切回来」通常在这个量级内，理应算作连续使用。
DEFAULT_MERGE_GAP = 120.0

_WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _secs(seg: Dict) -> float:
    return max(0.0, float(seg.get("seconds") or 0.0))


def _ts(seg: Dict, key: str) -> float:
    return float(seg.get(key) or 0.0)


def total_seconds(segments: Iterable[Dict]) -> float:
    return sum(_secs(s) for s in (segments or []))


def focus_seconds(segments: Iterable[Dict]) -> float:
    """「深度工作」总时长 = 类别为「工作」或「学习」的段之和。

    为什么把「学习」也算进来
        深度工作的本质是「专注在做正事」。只算「工作」的话，
        看两小时网课在进度环上是 0 —— 那是个明显说不通的数字，
        用户会以为采集坏了。

    与 `summary.longest_focus_seconds`（最长**单段**）口径一致：
    两者都引用 `category.FOCUS_CATEGORIES`，所以页面上两个数字不会互相打架。
    口径**只此一处** —— 以前两处各自写死 `"工作"`，改一处就会不一致。
    """
    return sum(
        _secs(s) for s in (segments or [])
        if (s.get("category") or "") in FOCUS_CATEGORIES
    )


def _local_date(ts: float):
    """本地自然日的 `(年, 月, 日)`。

    为什么不用 `day_start` 比时间戳
        `day_start` 内部走 `mktime` —— 在 Windows 上，1970-01-01 那天的
        **本地** 0 点落在 UTC 纪元之前，`mktime` 会抛 `OverflowError`。
        这里只问「是不是同一天」，`localtime` 就够了，而且对极早的时间戳
        也不会炸（数据坏了不该把整页带崩）。
        对正常数据，两者判「同一天」的结论完全一致。
    """
    lt = time.localtime(float(ts))
    return (lt.tm_year, lt.tm_mon, lt.tm_mday)


def _is_switch(prev: Dict, cur: Dict) -> bool:
    """相邻两段之间算不算一次「应用切换」。

    同一天 + 应用不同才算 —— **隔夜不算**。
    「昨天的最后一段 → 今天的第一段」不是用户切换了应用，是第二天重新开工。
    把它算进去有两个后果，而且都不会报错：
      ① 多日数据里每一天都凭空多出一次切换（周报的「切换了 N 次窗口」偏高）；
      ② 那次切换会归到**当天开工的那个小时** —— 趋势页于是说
         「早上 9 点最容易被打断」，而用户 9 点只是刚打开电脑。
    第 ② 条是 P2.14 目检时看出来的（`hour_switches` 的 08:00 桶在假数据里
    不为零，而假数据根本没有早上开工时的切换）。
    """
    if (cur.get("app") or "") == (prev.get("app") or ""):
        return False
    return _local_date(_ts(prev, "start_at")) == _local_date(_ts(cur, "start_at"))


def switch_count(segments: Iterable[Dict]) -> int:
    """应用切换次数 —— 相邻两段应用不同（且**同一天**）就算一次。"""
    segs = sorted(list(segments or []), key=lambda s: _ts(s, "start_at"))
    return sum(
        1 for i in range(1, len(segs)) if _is_switch(segs[i - 1], segs[i])
    )


def merge_segments(segments: Iterable[Dict], *, gap_seconds: float = DEFAULT_MERGE_GAP,
                   same_app_only: bool = True) -> List[Dict]:
    """把「同一应用、间隔很小」的相邻段合并成一段。

    为什么要合并
        频繁切窗口会留下大量十几秒的小段，直接画到 24 小时时间轴上
        就是一堆看不清的细线；「切走看一眼消息又切回来」本来也该算
        连续使用。合并后段数明显下降，时间轴才读得出来。

    为什么默认只合并**同应用**
        不同应用是不同色块 —— 合并了就等于把「在微信聊天」画成
        「在写代码」，是骗人。跨应用合并只在明确需要时才开。

    返回**新的** dict 列表，不修改入参。
    """
    segs = sorted(list(segments or []), key=lambda s: _ts(s, "start_at"))
    out: List[Dict] = []
    for seg in segs:
        item = {
            "app": seg.get("app") or "unknown",
            "category": seg.get("category") or OTHER,
            "start_at": _ts(seg, "start_at"),
            "end_at": _ts(seg, "end_at"),
            "seconds": _secs(seg),
            "key_rate": int(seg.get("key_rate") or 0),
        }
        if out:
            last = out[-1]
            gap = item["start_at"] - last["end_at"]
            same_app = item["app"] == last["app"]
            if gap <= float(gap_seconds) and (same_app or not same_app_only):
                last["end_at"] = max(last["end_at"], item["end_at"])
                last["seconds"] = last["end_at"] - last["start_at"]
                last["key_rate"] = max(last["key_rate"], item["key_rate"])
                continue
        out.append(item)
    return out


def weekday_label(ts: float) -> str:
    """`周一` … `周日`。"""
    return _WEEKDAY_CN[time.localtime(float(ts)).tm_wday]


def daily_totals(segments: Iterable[Dict], *, days: int = 7,
                 now: Optional[float] = None) -> List[Dict]:
    """按**自然日**聚合最近 N 天。

    返回按日期**升序**、且**包含没有记录的空日** ——
    柱状图的 x 轴必须连续，缺一天会让「周三和周五挨在一起」，
    看起来像连续两天都在工作。
    """
    days = max(1, int(days))
    now = time.time() if now is None else float(now)
    base = day_start(now)

    order: List[float] = []
    buckets: Dict[float, Dict] = {}
    for i in range(days - 1, -1, -1):
        start = base - i * DAY_SECONDS
        order.append(start)
        buckets[start] = {
            "start": start,
            "day": time.strftime("%m-%d", time.localtime(start)),
            "weekday": weekday_label(start),
            "total": 0.0,
            "focus": 0.0,
            "segments": 0,
        }

    for seg in (segments or []):
        # 用 start_at 归属 —— 跨天的段归到开始那天，避免同一段被算两次
        bucket = buckets.get(day_start(_ts(seg, "start_at")))
        if bucket is None:
            continue
        bucket["total"] += _secs(seg)
        if (seg.get("category") or "") in FOCUS_CATEGORIES:
            bucket["focus"] += _secs(seg)
        bucket["segments"] += 1

    return [buckets[s] for s in order]


def category_totals(segments: Iterable[Dict]) -> List[Dict]:
    """按类别聚合，按时长降序。"""
    acc: Dict[str, float] = {}
    for seg in (segments or []):
        cat = seg.get("category") or OTHER
        acc[cat] = acc.get(cat, 0.0) + _secs(seg)
    return [
        {"category": c, "seconds": v}
        for c, v in sorted(acc.items(), key=lambda kv: kv[1], reverse=True)
    ]


def top_apps(segments: Iterable[Dict], *, limit: int = 5) -> List[Dict]:
    """按应用聚合（时长 + 段数），按时长降序，取前 N 个。"""
    acc: Dict[str, Dict] = {}
    for seg in (segments or []):
        app = seg.get("app") or "unknown"
        item = acc.setdefault(
            app,
            {"app": app, "category": seg.get("category") or OTHER,
             "seconds": 0.0, "segments": 0},
        )
        item["seconds"] += _secs(seg)
        item["segments"] += 1
    ranked = sorted(acc.values(), key=lambda x: x["seconds"], reverse=True)
    return ranked[: max(0, int(limit))]


# ================================================================
# 按小时的打断分布（趋势页）
# ================================================================

HOURS_PER_DAY = 24


def hour_of_day(ts: float) -> int:
    """时刻落在一天的第几个小时（0–23，本地时区）。"""
    return int(time.localtime(float(ts)).tm_hour)


def hour_label(hour: int) -> str:
    """`10:00–11:00`。注意 23 点的右端是 `24:00` 而不是 `00:00` ——
    「23:00–00:00」会被读成倒着走。"""
    h = max(0, min(HOURS_PER_DAY - 1, int(hour)))
    return f"{h:02d}:00–{h + 1:02d}:00"


def hour_switches(segments: Iterable[Dict]) -> List[int]:
    """24 个桶：每个小时里发生了多少次**应用切换**。

    为什么按小时而不是按具体时刻
        用户能拿来行动的单位是「我上午十点总被打断」，不是「10:23:41 被打断」。

    为什么先排序
        `switch_count` 只看相邻两段，顺序错了会把同一对应用数很多次。
        这里显式按 `start_at` 排序，不依赖调用方给的顺序。

    切换**归到后一段所在的小时** —— 切换发生在「切到新应用」的那一刻。

    跨天的那一对不算（走 `_is_switch`）—— 否则每天开工的那个小时会凭空
    多一堆「打断」，把「最容易被打断的时段」指到早上。
    """
    segs = sorted(list(segments or []), key=lambda s: _ts(s, "start_at"))
    buckets = [0] * HOURS_PER_DAY
    for i in range(1, len(segs)):
        if _is_switch(segs[i - 1], segs[i]):
            buckets[hour_of_day(_ts(segs[i], "start_at"))] += 1
    return buckets


def busiest_hour(segments: Iterable[Dict]) -> Optional[int]:
    """切换最频繁的那个小时；一次切换都没有时返回 None。

    返回 None 而不是 0：0 点是合法答案（熬夜干活），
    用 0 表示「没有」会让页面显示「最易被打断的时段是 00:00–01:00」。
    """
    buckets = hour_switches(segments)
    top = max(buckets)
    return buckets.index(top) if top > 0 else None


# ================================================================
# 周期对比（趋势页）
# ================================================================

def period_bounds(days: int, now: Optional[float] = None):
    """本周期与上一周期的边界：`(cur_start, cur_end, prev_start, prev_end)`。

    周期口径与 `since_for_days` 一致 —— **自然日**，不是滚动 N×24 小时。
    上周期是**紧邻在前、同样长度**的一段，两段不重叠也不留缝。
    """
    days = max(1, int(days))
    now = time.time() if now is None else float(now)
    cur_end = now
    cur_start = day_start(now) - (days - 1) * DAY_SECONDS
    return (cur_start, cur_end, cur_start - days * DAY_SECONDS, cur_start)


def compare_periods(segments: Iterable[Dict], *, days: int = 7,
                    now: Optional[float] = None) -> Dict:
    """本周期 vs 紧邻的上一个同长周期。

    返回 `{"current": {...}, "previous": {...}, "delta_seconds": ...,
    "delta_ratio": ...}`；每个周期里有：
        `total` / `focus` / `switches` —— 三个汇总数字
        `count`                      —— 段数
        `segments`                   —— **切好的**分段列表（本周期的那一份）

    为什么要把切好的列表交出去
        趋势页向插件要的是 `days * 2` 天的原始列表（对比要用上周期）。
        页面若拿这份**混合**列表去算「时间构成」「按小时的打断」，
        算出来就是两个周期的量 —— 同一页上「本周期总时长」是 7 天、
        「时间构成」却是 14 天，两个数字互相矛盾，用户看不出来
        （P2.14 目检发现：概览 159 小时，时间构成却 236 小时）。
        切分口径只有这里一处，页面不再自己切。

    `delta_ratio` 为 `None` 表示**上周期是 0** —— 不能算出「增长了多少倍」，
    页面必须处理这个 None，否则会除零或显示「增长 0%」这种假话。
    """
    cur_start, cur_end, prev_start, prev_end = period_bounds(days, now)

    cur: List[Dict] = []
    prev: List[Dict] = []
    for seg in (segments or []):
        t = _ts(seg, "start_at")
        if cur_start <= t < cur_end:
            cur.append(seg)
        elif prev_start <= t < prev_end:
            prev.append(seg)

    def _pack(items: List[Dict]) -> Dict:
        ordered = sorted(items, key=lambda s: _ts(s, "start_at"))
        return {
            "total": total_seconds(ordered),
            "focus": focus_seconds(ordered),
            "switches": switch_count(ordered),
            "count": len(ordered),
            "segments": ordered,
        }

    current, previous = _pack(cur), _pack(prev)
    delta = current["total"] - previous["total"]
    return {
        "current": current,
        "previous": previous,
        "delta_seconds": delta,
        "delta_ratio": (delta / previous["total"]) if previous["total"] > 0 else None,
    }
