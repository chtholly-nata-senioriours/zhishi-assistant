# -*- coding: utf-8 -*-
"""前台窗口记录与还原。

为什么需要它
    唤起面板会抢走键盘焦点。用户关掉面板后，输入必须回到原来那个程序，
    否则「随手查一下」会变成「打断了手头的事」。

踩过的坑（S3 spike 实测）
    `SetForegroundWindow` 受 Windows 前台锁限制 —— 当前进程不是前台进程时，
    直接调用会**静默失败**（返回成功但窗口没被激活）。
    解法：先把当前线程 AttachThreadInput 到目标窗口所在线程，再设置前台窗口。
"""
from __future__ import annotations


class ForegroundGuard:
    """快照 / 还原前台窗口。"""

    def __init__(self):
        self._ok = False
        self._err = ""
        try:
            import win32api
            import win32con
            import win32gui
            import win32process

            self._api = win32api
            self._con = win32con
            self._gui = win32gui
            self._proc = win32process
            self._ok = True
        except Exception as e:  # noqa: BLE001
            self._err = f"{type(e).__name__}: {e}"

    @property
    def available(self) -> bool:
        return self._ok

    @property
    def error(self) -> str:
        return self._err

    # ----- 查询 -----

    def current(self) -> int:
        """当前前台窗口句柄；不可用时返回 0。"""
        return int(self._gui.GetForegroundWindow()) if self._ok else 0

    def snapshot(self) -> int:
        """记录当前前台窗口（唤出面板**之前**调用）。"""
        return self.current()

    def title_of(self, hwnd: int) -> str:
        if not self._ok or not hwnd:
            return ""
        try:
            return self._gui.GetWindowText(hwnd)
        except Exception:
            return ""

    # ----- 还原 -----

    def restore(self, hwnd: int) -> bool:
        """把焦点还给 hwnd。返回是否成功。"""
        if not self._ok or not hwnd:
            return False
        try:
            if not self._gui.IsWindow(hwnd):
                return False
            if self.current() == hwnd:
                return True
            if self._gui.IsIconic(hwnd):
                self._gui.ShowWindow(hwnd, self._con.SW_RESTORE)

            fg = self.current()
            cur_tid = self._api.GetCurrentThreadId()
            fg_tid = self._proc.GetWindowThreadProcessId(fg)[0] if fg else 0
            tgt_tid = self._proc.GetWindowThreadProcessId(hwnd)[0]

            attached = []
            try:
                for tid in (fg_tid, tgt_tid):
                    if tid and tid != cur_tid:
                        self._proc.AttachThreadInput(cur_tid, tid, True)
                        attached.append(tid)
                self._gui.SetForegroundWindow(hwnd)
            finally:
                for tid in attached:
                    try:
                        self._proc.AttachThreadInput(cur_tid, tid, False)
                    except Exception:
                        pass

            return self.current() == hwnd
        except Exception:
            return False
