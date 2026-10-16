# -*- coding: utf-8 -*-
"""时间范围与自然日语义（纯函数，零 Qt 依赖）。

为什么不能直接用 `now - days * 86400`
    那是**滚动窗口**：下午 3 点看「今天」，窗口从昨天下午 3 点开始 ——
    日报里混着昨天的数据，用户看到的「今天」和日历对不上。
    产品的「今天」必须是**今天 00:00** 起，这是自然日语义。

为什么不用 `datetime.date`
    下游全部用 `time.time()` 的时间戳（数据库里存的也是），
    在这里统一转换比让每个调用方各自折腾 `datetime` 更不容易出错。
"""
from __future__ import annotations

import time
from typing import Tuple

#: 一天的秒数（与 `store.DAY_SECONDS` 同值，此处独立定义避免循环导入）。
DAY_SECONDS = 86400.0


def day_start(ts: float) -> float:
    """`ts` 所在**自然日**的 00:00:00（本地时区）时间戳。

    用 `mktime(..., isdst=-1)` 让系统自己判断夏令时，
    不要手写 `ts - ts % 86400` —— 那算的是 UTC 日界，东八区会差 8 小时。
    """
    lt = time.localtime(float(ts))
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def same_day(a: float, b: float) -> bool:
    """两个时间戳是否落在同一个自然日。"""
    return day_start(a) == day_start(b)


def since_for_days(days: int, now: float) -> float:
    """「最近 N 天」的起点时间戳。

    N == 1 → 今天 00:00（**不是** 24 小时前）
    N == 7 → 今天 00:00 往前数 6 天，共 **7 个自然日**

    小于 1 的入参按 1 处理，避免出现「未来」的起点。
    """
    days = max(1, int(days))
    return day_start(now) - (days - 1) * DAY_SECONDS


def today_range(now: float) -> Tuple[float, float]:
    """今天 [00:00, 次日 00:00) 的起止时间戳。"""
    start = day_start(now)
    return start, start + DAY_SECONDS


def clock_hour(ts: float) -> int:
    """本地时间的**小时**（0–23），用于「到点了吗」这类判断。"""
    return int(time.localtime(float(ts)).tm_hour)


def human_day(ts: float) -> str:
    """给 UI 用的短日期：`10-13`。"""
    return time.strftime("%m-%d", time.localtime(float(ts)))
