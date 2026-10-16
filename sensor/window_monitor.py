"""窗口监听模块

检测当前活跃窗口的标题和进程信息，用于判断用户所处的工作场景。
支持 Windows 平台（使用 pygetwindow 或 pywin32）。

注意：
    - macOS/Linux 需要不同的实现（xprop 或 AppKit）
    - 仅获取窗口标题和进程名，不读取窗口内容
    - `is_foreground_fullscreen()` 只比较窗口与显示器的**矩形**，
      不读内容；它服务于「全屏免打扰」，不用来改分类

Events:
    WINDOW_ACTIVE: 活跃窗口变更时触发
        data: {"title": "窗口标题", "process": "进程名",
               "category": "工作/学习/沟通/娱乐/其他",
               "reason": "判定依据（一句话，不含标题原文）"}

分类口径不在这里
    「这个窗口算什么」的判定在 `engine.activity.category`（纯函数、有测试）。
    本模块只负责**取窗口**，取到之后交给它。以前判定逻辑长在这里，
    结果是它一条测试都没有 —— 详见那边的模块 docstring。
"""

import ctypes
import os
import time
import threading
import platform
from ctypes import wintypes
from typing import Dict, Optional, Tuple
from event_bus import event_bus

from engine.activity.category import explain

# 尝试导入平台相关的库
WIN32_AVAILABLE = False
try:
    if platform.system() == "Windows":
        import win32gui
        import win32process
        WIN32_AVAILABLE = True
except ImportError:
    pass


#: `OpenProcess` 的最小权限 —— 够查进程映像路径就行。
#: 不用 `PROCESS_QUERY_INFORMATION | PROCESS_VM_READ`（`GetModuleFileNameEx`
#: 要求的那套）：对受保护 / 提权进程它更容易 Access Denied。
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def query_process_name(pid: int) -> str:
    """取进程可执行文件名（小写，如 ``"code.exe"``）。

    为什么不用 psutil
        项目没装 psutil（见 `requirements.txt`），不为「一个字段」新增依赖。
    为什么用 QueryFullProcessImageNameW
        它只要 ``PROCESS_QUERY_LIMITED_INFORMATION``，对受保护进程
        比 `GetModuleFileNameEx` 更不容易失败。
    失败时回退 ``"pid_<n>"``
        拿不到名字不该让整个监听挂掉 —— 调用方按「未知应用」处理即可。
    """
    if not pid:
        return ""
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
        )
        if not handle:
            return f"pid_{pid}"
        try:
            size = wintypes.DWORD(260)
            buf = ctypes.create_unicode_buffer(260)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
            return f"pid_{pid}"
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return f"pid_{pid}"


#: `MonitorFromWindow` 的回退策略：找不到所属显示器时给最近的一个。
_MONITOR_DEFAULTTONEAREST = 2


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def is_foreground_fullscreen(tolerance: int = 2) -> bool:
    """前台窗口是否**铺满**了所在显示器（只读几何，不含任何内容）。

    用途：**全屏 = 免打扰信号**。
        全屏大概率是在看视频 / 开会 / 演示 —— 这时候弹「收工小结」
        最招人烦。所以判定为全屏时直接放弃本次提醒，等下次时机。

    **不用来改分类**
        全屏看文档也是全屏。拿它把「工作」改成「娱乐」会误判，
        所以分类仍然只看标题与进程名。

    与「最大化」怎么区分
        最大化窗口止步于**工作区**（任务栏之外），与 `rcMonitor` 会差
        一条任务栏的高度 —— 所以不会被误判成全屏。
    """
    if platform.system() != "Windows":
        return False
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False

        rect = _RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False

        hmon = user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
        if not hmon:
            return False

        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return False

        mon = info.rcMonitor
        return (
            abs(rect.left - mon.left) <= tolerance
            and abs(rect.top - mon.top) <= tolerance
            and abs(rect.right - mon.right) <= tolerance
            and abs(rect.bottom - mon.bottom) <= tolerance
        )
    except Exception:  # noqa: BLE001 —— 探测失败按「不是全屏」处理（宁可多推一次）
        return False


class WindowMonitor:
    """窗口监听器 - 检测活跃窗口变化"""

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

            # 获取进程名（真实 exe 名，如 "code.exe"；拿不到才回退 "pid_<n>"）
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process_name = query_process_name(pid)
            except Exception:
                process_name = "unknown"

            return {
                "title": title,
                "process": process_name,
            }
        except Exception:
            return None

    def _classify_window(self, info: Dict) -> Tuple[str, str]:
        """判定窗口类别，返回 `(分类, 依据)`。

        实现全在 `engine.activity.category.explain` —— 那边是纯函数、有测试，
        覆盖了「digital 不该命中 git」「浏览器不该默认算工作」这类真实误判。
        这里只做一层转接：本模块的职责是取窗口，不是定义「什么算工作」。
        """
        return explain(info.get("process") or "", info.get("title") or "")

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

                    # 分类 + 依据（依据只进事件，不落库 —— 见 store 的表结构）
                    category, reason = self._classify_window(info)
                    info["category"] = category
                    info["reason"] = reason

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
