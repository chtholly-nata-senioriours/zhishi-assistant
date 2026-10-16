# -*- coding: utf-8 -*-
"""「收工小结」的时机判定（纯函数，零 Qt 依赖）。

设计目标：**主动，但极克制**。
    用户不该为了看建议而记着去点按钮；但也不该被频繁打扰。
    所以策略是「一天最多一次」外加一串免打扰条件 ——
    宁可少推，也不能烦人。这是本模块存在的全部理由。

为什么做成纯函数
    时机逻辑最容易写成一堆 `if` 散落在插件的回调里，然后没法测。
    这里输入全是标量、输出是 `(是否提醒, 原因)`，原因还能直接当日志用。
"""
from __future__ import annotations

from typing import Optional, Tuple

from .schedule import clock_hour, same_day

#: 默认「收工时间」：本地时间过了这个点才考虑提醒。
DEFAULT_NUDGE_HOUR = 18


def should_nudge(
    *,
    now: float,
    enabled: bool,
    nudge_enabled: bool,
    nudge_hour: int = DEFAULT_NUDGE_HOUR,
    last_nudged_at: Optional[float] = None,
    has_data_today: bool = False,
    fullscreen: bool = False,
    timer_running: bool = False,
    away: bool = False,
) -> Tuple[bool, str]:
    """判断此刻是否该推「收工小结」。

    返回 `(是否提醒, 原因)`。**原因永远返回**，即使结果为 False ——
    出问题时看日志就知道是被哪一条挡下的，不用猜。

    判定顺序刻意把「打扰类」条件放在前面：全屏 / 专注中 / 人不在时
    连数据都不用查，直接放弃。
    """
    if not enabled:
        return False, "采集未开启"
    if not nudge_enabled:
        return False, "用户关闭了主动提醒"
    if fullscreen:
        # 全屏大概率在看视频 / 开会 / 演示 —— 这时候冒出来最招人烦
        return False, "全屏中，免打扰"
    if timer_running:
        return False, "专注计时中，免打扰"
    if away:
        return False, "用户不在，等回来再说"
    if not has_data_today:
        return False, "今天还没有活动记录"
    if clock_hour(now) < int(nudge_hour):
        return False, f"还没到 {int(nudge_hour)} 点"
    if last_nudged_at is not None and same_day(float(last_nudged_at), now):
        return False, "今天已经提醒过"
    return True, "可以提醒"
