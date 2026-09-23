"""定时触发模块

按预设周期触发定时事件，包括：
- 整点触发 (TIME_HOURLY)
- 每30分钟触发 (TIME_30MIN)
- 每5分钟触发 (TIME_TICK)
- 自定义定时器

Events:
    TIME_HOURLY: 整点触发
    TIME_30MIN: 每30分钟触发
    TIME_TICK: 每5分钟触发（基础心跳）
"""

import time
import threading
from typing import Callable, List, Dict
from event_bus import event_bus, register_event_type


class TimeTrigger:
    """定时触发器 - 按预设周期触发事件"""

    def __init__(self):
        self._running = False
        self._thread = None
        self._check_interval = 1  # 基础检查间隔 1 秒
        self._lock = threading.Lock()

        # 定时器注册表
        self._timers: Dict[str, Dict] = {}

        # 上次触发时间记录
        self._last_hour = -1
        self._last_30min = -1
        self._last_5min = -1

    def start(self):
        """启动定时触发器"""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._timer_loop, daemon=True)
        self._thread.start()
        print("定时触发器已启动")

    def stop(self):
        """停止定时触发器"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        print("定时触发器已停止")

    def add_timer(self, timer_id: str, interval: int, callback: Callable = None,
                  repeat: bool = True, data: Dict = None) -> bool:
        """
        添加自定义定时器

        Args:
            timer_id: 定时器唯一标识
            interval: 间隔秒数
            callback: 回调函数
            repeat: 是否重复
            data: 回调时传递的数据

        Returns:
            是否添加成功
        """
        # 注册动态事件类型，避免发布时被事件总线告警/丢弃
        register_event_type(f"TIMER_{timer_id.upper()}")

        with self._lock:
            self._timers[timer_id] = {
                "interval": interval,
                "callback": callback,
                "repeat": repeat,
                "data": data or {},
                "last_trigger": time.time(),
                "trigger_count": 0,
            }
            return True

    def remove_timer(self, timer_id: str) -> bool:
        """
        移除定时器

        Args:
            timer_id: 定时器标识

        Returns:
            是否移除成功
        """
        with self._lock:
            if timer_id in self._timers:
                del self._timers[timer_id]
                return True
            return False

    def _timer_loop(self):
        """定时器循环"""
        while self._running:
            now = time.localtime()
            current_time = time.time()

            # ----- 预设定时触发 -----

            # 整点触发
            if now.tm_min == 0 and now.tm_sec < self._check_interval:
                if self._last_hour != now.tm_hour:
                    self._last_hour = now.tm_hour
                    event_bus.publish("TIME_HOURLY", {
                        "hour": now.tm_hour,
                        "formatted": time.strftime("%H:%M:00")
                    })

            # 每30分钟触发 (xx:00 和 xx:30)
            if now.tm_min in [0, 30] and now.tm_sec < self._check_interval:
                minute_key = now.tm_hour * 2 + (now.tm_min // 30)
                if self._last_30min != minute_key:
                    self._last_30min = minute_key
                    event_bus.publish("TIME_30MIN", {
                        "hour": now.tm_hour,
                        "minute": now.tm_min,
                        "formatted": time.strftime("%H:%M:00")
                    })

            # 每5分钟触发 (心跳)
            five_min_block = (now.tm_hour * 60 + now.tm_min) // 5
            if now.tm_sec < self._check_interval:
                if self._last_5min != five_min_block:
                    self._last_5min = five_min_block
                    event_bus.publish("TIME_TICK", {
                        "hour": now.tm_hour,
                        "minute": now.tm_min,
                    })

            # ----- 自定义定时器 -----
            with self._lock:
                timers_snapshot = list(self._timers.items())

            for timer_id, timer in timers_snapshot:
                if current_time - timer["last_trigger"] >= timer["interval"]:
                    # 发布事件（锁外执行避免死锁）
                    event_data = {
                        "timer_id": timer_id,
                        "trigger_count": timer["trigger_count"] + 1,
                        **timer["data"]
                    }
                    event_bus.publish(f"TIMER_{timer_id.upper()}", event_data)

                    # 执行回调（锁外）
                    if timer["callback"]:
                        try:
                            timer["callback"](event_data)
                        except Exception as e:
                            print(f"定时器回调错误 [{timer_id}]: {e}")

                    # 更新状态在锁内进行
                    with self._lock:
                        if timer_id not in self._timers:
                            continue
                        self._timers[timer_id]["last_trigger"] = current_time
                        self._timers[timer_id]["trigger_count"] += 1

                        # 非重复定时器，移除
                        if not timer["repeat"]:
                            del self._timers[timer_id]

            time.sleep(self._check_interval)
