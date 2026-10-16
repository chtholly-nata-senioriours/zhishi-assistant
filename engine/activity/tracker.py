# -*- coding: utf-8 -*-
"""活动分段器 —— 把「窗口切换事件」合并成有起止时间的活动段。

为什么不直接落事件
    `WINDOW_ACTIVE` 是**瞬时**事件：只在切换时发一次，不带「持续了多久」。
    直接落库只会得到一串时间点，算不出「你在 VS Code 待了 2 小时」。
    所以这里维护一个「当前段」，等切换时才把上一段结算入库。

为什么不自己订阅事件
    `record()` 是纯逻辑，由调用方（插件）从事件总线接过来。
    这样本模块不 import `event_bus`，可以脱离 Qt 与全局单例单测。

线程模型
    `record()` 由事件回调调用（可能在任意线程）。内部只碰自己的字段
    和 `ActivityStore`（自带锁），不碰 Qt。
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

from .store import ActivityStore

#: 短于这个时长的段直接丢弃 —— Alt+Tab 扫过一排窗口会造出一堆
#: 1～2 秒的碎片，既没信息量又会把「总时长」撑得虚高。
DEFAULT_MIN_SEGMENT_SECONDS = 5.0

#: 空闲超过这个秒数就算「人不在」。默认 5 分钟 ——
#: 比这更短会把「停下来读一段代码」误判成离开。
DEFAULT_AWAY_SECONDS = 300.0


class ActivityTracker:
    """维护「当前活动段」，切换时结算入库。

    空闲剪裁（`idle_provider`）
        没有它的时候，「打开 Chrome → 出去吃饭 → 回来」会被记成
        「Chrome 3 小时」。给了 `idle_provider` 之后，结算时会把
        「最后一次输入之后」的那段剪掉，时长才对得上用户直觉。

        为什么还要 `tick()`
            只在切窗口时剪是不够的：用户回来第一件事往往是切窗口，
            那一刻空闲已经归零，剪不到了。`tick()` 由定时器周期性调用，
            在**用户还不在的时候**就把段收尾，才剪得准。
    """

    def __init__(
        self,
        store: ActivityStore,
        key_rate_provider: Optional[Callable[[], int]] = None,
        idle_provider: Optional[Callable[[], float]] = None,
        clock: Callable[[], float] = time.time,
        min_segment_seconds: float = DEFAULT_MIN_SEGMENT_SECONDS,
        exclude_apps: Optional[List[str]] = None,
        away_seconds: float = DEFAULT_AWAY_SECONDS,
    ):
        self._store = store
        self._key_rate_provider = key_rate_provider
        self._idle_provider = idle_provider
        self._clock = clock
        self._min_segment_seconds = max(0.0, float(min_segment_seconds))
        self._away_seconds = max(1.0, float(away_seconds))
        # 归一化：小写 + 去空白，避免 "Chrome.exe " 与 "chrome.exe" 被当成两个应用
        self._excluded = {
            str(a).strip().lower() for a in (exclude_apps or []) if str(a).strip()
        }
        self._current: Optional[Dict] = None
        #: 离开前最后停留的应用 —— 回来后据此续上，避免「回来不切窗口就丢数据」
        self._last: Optional[Dict] = None
        self._away = False

    # ----- 对外 -----

    @property
    def current(self) -> Optional[Dict]:
        """当前正在累积的段（供 UI 显示「当前在 xxx，已 12 分钟」）。"""
        return dict(self._current) if self._current else None

    @property
    def excluded_apps(self) -> List[str]:
        return sorted(self._excluded)

    def record(self, app: str, category: str, at: Optional[float] = None) -> None:
        """记录一次「此刻活跃的是哪个应用」。

        同一应用重复上报**不切段** —— `WINDOW_ACTIVE` 会因为标题变化
        （换标签页、改文件名）而反复触发，但用户并没有换应用。
        """
        at = self._clock() if at is None else float(at)
        app = (app or "").strip().lower()

        if not app or app in self._excluded:
            # 被排除的应用（或拿不到名字）：结束当前段，且不开新段，
            # 这段时间就当作「未记录」，而不是硬塞进「其他」。
            self._close(at)
            return

        if self._current is not None and self._current["app"] == app:
            self._current["end_at"] = at
            self._last = dict(self._current)
            return

        self._close(at)
        self._away = False
        self._current = {
            "app": app,
            "category": category or "其他",
            "start_at": at,
            "end_at": at,
        }
        self._last = dict(self._current)

    def flush(self, at: Optional[float] = None) -> None:
        """结束当前段并入库。

        用**当前时间**作为结束点 —— 用户可能在同一应用里待了很久没切窗口，
        此时 `WINDOW_ACTIVE` 不会再触发，只能以 flush 时刻收尾。
        """
        self._close(self._clock() if at is None else float(at))

    def tick(self, at: Optional[float] = None) -> bool:
        """周期性检查「人还在不在」。返回检查后是否处于离开状态。

        由调用方接到定时器上（本项目复用 `TIME_TICK`，5 分钟一次）。
        两件事：
          1. 已经离开 → **当场**把当前段收尾（结束点拉回最后一次输入），
             而不是等到切窗口才发现 —— 那时空闲已经归零，剪不到了。
          2. 离开后又回来 → 从「最后一次输入的时刻」续上离开前的应用。
             不续的话，用户回来不切窗口就继续用，这段会整个丢失。
        """
        at = self._clock() if at is None else float(at)
        idle = self._idle_seconds()

        if idle >= self._away_seconds:
            self._close(at, idle=idle)
            self._away = True
            return True

        if self._away:
            self._away = False
            last = self._last
            if last is not None:
                start = max(0.0, at - idle)
                self._current = {
                    "app": last["app"],
                    "category": last.get("category") or "其他",
                    "start_at": start,
                    "end_at": start,
                }
        return False

    def is_away(self) -> bool:
        """此刻用户是否不在（供「收工小结」免打扰判断）。"""
        return self._idle_seconds() >= self._away_seconds

    # ----- 内部 -----

    def _close(self, at: float, idle: Optional[float] = None) -> None:
        cur = self._current
        self._current = None
        if cur is None:
            return

        end = float(at)
        idle_s = self._idle_seconds() if idle is None else max(0.0, float(idle))
        if idle_s > 0:
            # 把「最后一次输入之后」的时间剪掉 —— 人不在时不该计时长
            end = min(end, float(at) - idle_s)
        if end <= float(cur["start_at"]):
            # 整段都落在「人不在」里，没有可记录的内容
            return

        seconds = end - float(cur["start_at"])
        if seconds < self._min_segment_seconds:
            return

        self._store.add_segment(
            cur["app"], cur["category"], cur["start_at"], end,
            self._key_rate(),
        )

    def _idle_seconds(self) -> float:
        if self._idle_provider is None:
            return 0.0
        try:
            return max(0.0, float(self._idle_provider() or 0.0))
        except Exception:  # noqa: BLE001 —— 探针失败按「人一直在」处理
            return 0.0

    def _key_rate(self) -> int:
        if self._key_rate_provider is None:
            return 0
        try:
            return int(self._key_rate_provider() or 0)
        except Exception:
            return 0
