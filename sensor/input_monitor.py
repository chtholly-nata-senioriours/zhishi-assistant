"""输入监听模块

监听键盘敲击频率和鼠标活动，将高频活动转换为事件发送到事件总线。
使用 pynput 库进行跨平台的输入监听。

注意：
    - 键盘监听仅统计敲击频率，不记录具体按键内容
    - 需要管理员/用户权限运行（部分系统）
    - 被杀毒软件误报时可添加信任

Events:
    KEYBOARD_HIGH_RATE: 键盘高频敲击 (>60次/30秒)
    MOUSE_MOVE: 鼠标移动
    MOUSE_CLICK: 鼠标点击
"""

import time
import threading
from typing import Callable, Optional
from collections import deque

from event_bus import event_bus

try:
    from pynput import keyboard, mouse
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False
    print("警告: pynput 未安装，输入监听功能将不可用。运行: pip install pynput")


class InputMonitor:
    """输入监听器 - 监控键盘和鼠标活动"""

    def __init__(self):
        # 键盘统计
        self._key_buffer = deque()  # 存储按键时间戳
        self._key_buffer_duration = 30  # 统计窗口（秒）
        self._focus_threshold = 60    # 专注阈值（次/30秒）

        # 鼠标统计
        self._last_mouse_time = 0
        self._last_mouse_pos = None       # 上次鼠标位置
        self._mouse_move_threshold = 0.1  # 鼠标移动事件间隔（秒）
        self._mouse_move_min_distance = 5  # 最小移动像素（防抖/噪声过滤）

        # 运行状态
        self._running = False
        self._listeners = []
        self._check_thread = None
        self._lock = threading.Lock()

    def start(self):
        """启动输入监听"""
        if self._running:
            return

        self._running = True

        if not PYNPUT_AVAILABLE:
            print("pynput 不可用，跳过输入监听")
            self._running = False
            return

        try:
            # 键盘监听
            keyboard_listener = keyboard.Listener(
                on_press=self._on_key_press,
                suppress=False  # 不拦截按键
            )
            keyboard_listener.start()
            self._listeners.append(keyboard_listener)

            # 鼠标监听
            mouse_listener = mouse.Listener(
                on_move=self._on_mouse_move,
                on_click=self._on_mouse_click
            )
            mouse_listener.start()
            self._listeners.append(mouse_listener)

            # 启动检查线程
            self._check_thread = threading.Thread(target=self._check_loop, daemon=True)
            self._check_thread.start()

            print("输入监听已启动")

        except Exception as e:
            print(f"启动输入监听失败: {e}")
            self._running = False

    def stop(self):
        """停止输入监听"""
        self._running = False

        for listener in self._listeners:
            try:
                listener.stop()
            except Exception:
                pass
        self._listeners.clear()

        print("输入监听已停止")

    # --- 键盘处理 ---

    def _on_key_press(self, key):
        """键盘按下回调"""
        now = time.time()
        with self._lock:
            # 清理过期数据
            self._clean_key_buffer(now)
            # 添加新按键
            self._key_buffer.append(now)

    def _clean_key_buffer(self, now: float):
        """清理过期的按键记录"""
        while self._key_buffer and now - self._key_buffer[0] > self._key_buffer_duration:
            self._key_buffer.popleft()

    def get_key_rate(self) -> float:
        """获取当前键盘敲击频率（次/30秒）"""
        now = time.time()
        with self._lock:
            self._clean_key_buffer(now)
            return len(self._key_buffer)

    # --- 鼠标处理 ---

    def _on_mouse_move(self, x, y):
        """鼠标移动回调"""
        now = time.time()
        # 时间防抖：避免过于频繁的事件
        if now - self._last_mouse_time <= self._mouse_move_threshold:
            return
        # 距离防抖：过滤微小抖动（如传感器噪声）
        if self._last_mouse_pos is not None:
            dx = x - self._last_mouse_pos[0]
            dy = y - self._last_mouse_pos[1]
            if (dx * dx + dy * dy) < self._mouse_move_min_distance * self._mouse_move_min_distance:
                return
        self._last_mouse_time = now
        self._last_mouse_pos = (x, y)
        event_bus.publish("MOUSE_MOVE", {"x": x, "y": y})

    def _on_mouse_click(self, x, y, button, pressed):
        """鼠标点击回调"""
        if pressed:
            event_bus.publish("MOUSE_CLICK", {
                "x": x,
                "y": y,
                "button": str(button)
            })

    # --- 检查循环 ---

    def _check_loop(self):
        """定期检查键盘频率"""
        while self._running:
            rate = self.get_key_rate()
            if rate >= self._focus_threshold:
                event_bus.publish("KEYBOARD_HIGH_RATE", {
                    "rate": rate,
                    "threshold": self._focus_threshold
                })
            time.sleep(5)  # 每5秒检查一次
