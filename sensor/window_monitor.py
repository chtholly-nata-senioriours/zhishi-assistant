"""窗口监听模块

检测当前活跃窗口的标题和进程信息，用于判断用户所处的工作场景。
支持 Windows 平台（使用 pygetwindow 或 pywin32）。

注意：
    - macOS/Linux 需要不同的实现（xprop 或 AppKit）
    - 仅获取窗口标题和进程名，不读取窗口内容

Events:
    WINDOW_ACTIVE: 活跃窗口变更时触发
        data: {"title": "窗口标题", "process": "进程名", "category": "工作/娱乐/其他"}
"""

import time
import threading
import platform
from typing import Dict, Optional, Set
from event_bus import event_bus

# 尝试导入平台相关的库
WIN32_AVAILABLE = False
try:
    if platform.system() == "Windows":
        import win32gui
        import win32process
        WIN32_AVAILABLE = True
except ImportError:
    pass


class WindowMonitor:
    """窗口监听器 - 检测活跃窗口变化"""

    # 工作类应用关键词（用于判断专注状态）
    WORK_KEYWORDS = {
        "code", "visual studio", "pycharm", "intellij", "idea",
        "eclipse", "vim", "nvim", "sublime", "atom",
        "word", "excel", "powerpoint", "onenote",
        "notion", "obsidian", "typora", "markdown",
        "browser", "chrome", "firefox", "edge",
        "terminal", "cmd", "powershell", "git",
        "figma", "sketch", "photoshop", "illustrator",
        "slack", "teams", "zoom", "meeting",
    }

    # 娱乐类应用关键词
    ENTERTAIN_KEYWORDS = {
        "game", "steam", "epic", "origin", "uplay",
        "bilibili", "youtube", "netflix", "spotify",
    }

    def __init__(self, check_interval: float = 2.0):
        self.check_interval = check_interval  # 检查间隔（秒）
        self._running = False
        self._thread = None
        self._last_window = None
        self._lock = threading.Lock()

        # 缓存当前窗口信息
        self._current_info = {
            "title": "",
            "process": "",
            "category": "其他"
        }

    def start(self):
        """启动窗口监听"""
        if self._running:
            return

        if not WIN32_AVAILABLE and platform.system() == "Windows":
            print("警告: win32gui 不可用，窗口监听功能将受限")
            return

        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        print("窗口监听已启动")

    def stop(self):
        """停止窗口监听"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)
        print("窗口监听已停止")

    def get_current_window(self) -> Dict:
        """获取当前窗口信息"""
        with self._lock:
            return dict(self._current_info)

    def _get_active_window_info(self) -> Optional[Dict]:
        """
        获取当前活跃窗口信息

        Returns:
            包含窗口信息的字典，或 None
        """
        if not WIN32_AVAILABLE:
            return None

        try:
            # 获取当前活跃窗口的句柄
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None

            # 获取窗口标题
            title = win32gui.GetWindowText(hwnd).lower()

            # 获取进程名
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                # 获取进程名（简化处理，实际可能需要 psutil）
                process_name = f"pid_{pid}"
            except Exception:
                process_name = "unknown"

            return {
                "title": title,
                "process": process_name,
            }
        except Exception:
            return None

    def _classify_window(self, info: Dict) -> str:
        """
        根据窗口标题和进程名分类窗口类型

        Args:
            info: 窗口信息字典

        Returns:
            分类结果: "工作" / "娱乐" / "其他"
        """
        full_text = f"{info.get('title', '')} {info.get('process', '')}".lower()

        for keyword in self.WORK_KEYWORDS:
            if keyword in full_text:
                return "工作"

        for keyword in self.ENTERTAIN_KEYWORDS:
            if keyword in full_text:
                return "娱乐"

        return "其他"

    def _monitor_loop(self):
        """监控循环 - 定期检查窗口变化"""
        while self._running:
            try:
                info = self._get_active_window_info()
                if info is None:
                    time.sleep(self.check_interval)
                    continue

                # 检测窗口是否变化（比较标题）
                new_title = info.get("title", "")
                if new_title != self._last_window:
                    self._last_window = new_title

                    # 分类
                    category = self._classify_window(info)
                    info["category"] = category

                    # 更新缓存
                    with self._lock:
                        self._current_info = info

                    # 发布事件
                    event_bus.publish("WINDOW_ACTIVE", info)

            except Exception as e:
                print(f"窗口监听错误: {e}")

            time.sleep(self.check_interval)

    def is_focus_mode_possible(self) -> bool:
        """判断当前是否可能处于工作/专注模式"""
        current = self.get_current_window()
        return current.get("category") == "工作"
