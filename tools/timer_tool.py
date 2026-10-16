"""番茄钟工具模块

功能：
    - 25分钟专注计时 + 5分钟休息计时
    - 支持暂停/继续/停止
    - 完成后触发事件和通知
    - 统计今日完成数

Events:
    TIMER_START: 番茄钟开始
    TIMER_END: 番茄钟结束
    TIMER_TICK: 每秒进度更新
    TIMER_PAUSE: 番茄钟暂停
    TIMER_RESUME: 番茄钟恢复

Usage:
    from tools.timer_tool import TomatoTimer

    timer = TomatoTimer()
    timer.start("work")            # 按构造时的 work_duration
    timer.start("work", minutes=45)  # 或指定这一次的时长
    # ...
    timer.pause()
    timer.resume()
    timer.stop()
"""

import time
import threading
from enum import Enum, auto
from typing import Optional, Callable, Dict
from event_bus import event_bus


class TimerState(Enum):
    """计时器状态"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"


class TomatoTimer:
    """番茄钟计时器"""

    def __init__(self,
                 work_duration: int = 25,       # 工作时长（分钟）
                 break_duration: int = 5,       # 休息时长（分钟）
                 long_break_duration: int = 15,  # 长休息时长（分钟）
                 long_break_interval: int = 4):  # 长休息间隔（几个番茄钟）

        self.work_duration = work_duration
        self.break_duration = break_duration
        self.long_break_duration = long_break_duration
        self.long_break_interval = long_break_interval

        # 当前状态
        self.state = TimerState.IDLE
        self.timer_type = "work"  # work / break / long_break

        # 计时相关
        self._total_seconds = 0
        self._remaining_seconds = 0
        self._start_time = 0
        self._paused_remaining = 0

        # 统计
        self._today_count = 0
        self._session_count = 0

        # 线程
        self._timer_thread = None
        self._running = False
        self._lock = threading.Lock()
        #: 「第几轮计时」。每次 start / resume / stop 都 +1，线程带着自己那轮
        #: 的号进来，发现号变了就直接退出。
        #:
        #: 为什么必须有它（P2.18 修的真 bug）
        #:     旧线程在 `time.sleep(1)` 里睡着时，`stop()` 把 `_running` 置假；
        #:     用户接着开新一轮，`_running` 又被置真 —— 旧线程醒来看到的
        #:     是「还在跑」，于是**两个线程一起倒扣秒数**，倒计时跑成两倍速。
        #:     以前 `stop()` 只有番茄钟对话框能触发，很难撞上；
        #:     P2.18 给「今日」页加了「结束专注」按钮，`停 → 再开` 变成常规操作，
        #:     不修就是必现。
        self._epoch = 0

    @property
    def remaining_minutes(self) -> int:
        """剩余分钟"""
        return self._remaining_seconds // 60

    @property
    def remaining_seconds_display(self) -> int:
        """剩余秒数（不包括整分钟）"""
        return self._remaining_seconds % 60

    @property
    def progress(self) -> float:
        """进度百分比 (0-1)"""
        if self._total_seconds <= 0:
            return 0.0
        return 1.0 - (self._remaining_seconds / self._total_seconds)

    @property
    def formatted_time(self) -> str:
        """格式化的剩余时间 (MM:SS)"""
        minutes = self._remaining_seconds // 60
        seconds = self._remaining_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    # ----- 控制方法 -----

    def start(self, timer_type: str = "work", minutes: int = 0) -> bool:
        """
        开始计时

        Args:
            timer_type: "work" 或 "break" 或 "long_break"
            minutes: 只对 `work` 有意义 —— 本次要专注多少分钟。
                0 / 负数 / 非数字时用 `self.work_duration`。

                为什么需要这个参数（P2.18 修的真 bug）
                    以前 `start("work")` 只认 `self.work_duration`，
                    调用方给的分钟数**被静默丢掉**。建议卡上写着
                    「开始 45 分钟专注」，点下去实际跑的是 25 分钟 ——
                    界面说的和做的不一致，而且从日志里看不出来。
                    时长是「这一次」的属性，不该只能靠构造时的全局值决定。

        Returns:
            是否成功启动
        """
        with self._lock:
            if self.state == TimerState.RUNNING:
                return False

            self.timer_type = timer_type

            # 根据类型设置时长
            if timer_type == "work":
                try:
                    wanted = int(minutes)
                except (TypeError, ValueError):
                    wanted = 0
                self._total_seconds = (wanted if wanted > 0 else self.work_duration) * 60
            elif timer_type == "break":
                self._total_seconds = self.break_duration * 60
            elif timer_type == "long_break":
                self._total_seconds = self.long_break_duration * 60
            else:
                return False

            self._remaining_seconds = self._total_seconds
            self.state = TimerState.RUNNING
            self._running = True

        # 启动计时线程
        self._spawn()

        # 发布事件
        event_bus.publish("TIMER_START", {
            "type": timer_type,
            "duration": self._total_seconds,
        })

        return True

    def pause(self) -> bool:
        """暂停计时"""
        with self._lock:
            if self.state != TimerState.RUNNING:
                return False

            self.state = TimerState.PAUSED
            self._paused_remaining = self._remaining_seconds

        event_bus.publish("TIMER_PAUSE", {
            "type": self.timer_type,
            "remaining": self._remaining_seconds,
        })

        return True

    def resume(self) -> bool:
        """恢复计时"""
        with self._lock:
            if self.state != TimerState.PAUSED:
                return False

            self.state = TimerState.RUNNING
            self._remaining_seconds = self._paused_remaining

        # 重新开始计时
        self._running = True
        self._spawn()

        event_bus.publish("TIMER_RESUME", {
            "type": self.timer_type,
            "remaining": self._remaining_seconds,
        })

        return True

    def stop(self) -> bool:
        """停止计时"""
        was_running = self._running
        self._running = False

        with self._lock:
            self.state = TimerState.IDLE
            # 换号：还在 `sleep` 里的旧线程醒来会发现号变了，直接退出 ——
            # 否则用户「停 → 再开」时会有两个线程一起倒扣秒数（倒计时两倍速）。
            self._epoch += 1

        if was_running:
            event_bus.publish("TIMER_END", {
                "type": self.timer_type,
                "completed": False,
                "reason": "stopped",
            })

        return True

    def _spawn(self) -> None:
        """开一轮新的计时线程，并给它一个轮次号。"""
        with self._lock:
            self._epoch += 1
            epoch = self._epoch
        self._timer_thread = threading.Thread(
            target=self._timer_loop, args=(epoch,), daemon=True
        )
        self._timer_thread.start()

    def _timer_loop(self, epoch: int):
        """计时线程循环。

        `epoch` 是这一轮的号。**每处读共享状态前都要先核对号**：
        号对不上说明这一轮已经被 `stop()` / 新一轮取代，直接退出 ——
        不然旧线程会和新的那个一起倒扣秒数。
        """
        while self._running and self._remaining_seconds > 0:
            with self._lock:
                if epoch != self._epoch:
                    return
            # 每秒更新一次
            time.sleep(1)

            with self._lock:
                if epoch != self._epoch:
                    return
                if self.state != TimerState.RUNNING:
                    break

                self._remaining_seconds -= 1

                # 发布进度更新
                event_bus.publish("TIMER_TICK", {
                    "type": self.timer_type,
                    "remaining": self._remaining_seconds,
                    "total": self._total_seconds,
                    "progress": self.progress,
                    "formatted": self.formatted_time,
                })

        # 计时结束（只有当前这一轮的线程才有资格宣布）
        with self._lock:
            if epoch != self._epoch:
                return
            finished = self._remaining_seconds <= 0 and self._running
        if finished:
            self._on_timer_finished()

    def _on_timer_finished(self):
        """计时完成处理"""
        self._running = False

        with self._lock:
            self.state = TimerState.FINISHED

        # 更新统计
        if self.timer_type == "work":
            self._session_count += 1
            self._today_count += 1

        event_bus.publish("TIMER_END", {
            "type": self.timer_type,
            "completed": True,
            "duration": self._total_seconds,
            "session_count": self._session_count,
        })

    # ----- 查询方法 -----

    def get_status(self) -> Dict:
        """获取当前状态"""
        return {
            "state": self.state.value,
            "type": self.timer_type,
            "progress": self.progress,
            "remaining": self._remaining_seconds,
            "total": self._total_seconds,
            "formatted": self.formatted_time,
            "session_count": self._session_count,
            "today_count": self._today_count,
        }

    def is_running(self) -> bool:
        """是否正在运行"""
        return self.state == TimerState.RUNNING

    def is_paused(self) -> bool:
        """是否暂停"""
        return self.state == TimerState.PAUSED
