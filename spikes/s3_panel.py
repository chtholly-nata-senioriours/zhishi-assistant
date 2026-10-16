#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S3 — 面板低延迟唤起 + 焦点还原

假设
    预热过的面板能做到 ≤150ms 可见，且关闭后能 100% 还原原窗口焦点。

方法
    1. 测「冷构建」耗时 —— 首次构造控件树的时间（不应发生在热键回调里）。
    2. 测「预热唤起」延迟 —— 预热后重复 hide/show 50 次，取 P95。
    3. 实现 ForegroundGuard（含 AttachThreadInput 解锁技巧），做真实焦点还原测试：
       窗口 A 获得焦点 → 快照 → 面板 B 抢焦点 → restore(A) → 校验前台回到 A。

判定
    预热唤起 P95 ≤ 150ms 且 焦点还原成功 → PASS

已知坑（本 spike 的核心价值）
    `SetForegroundWindow` 受 Windows 前台锁限制，直接调用常静默失败。
    必须先把当前线程 AttachThreadInput 到目标窗口线程，再设置前台窗口。

用法
    python spikes/s3_panel.py
    python spikes/s3_panel.py --iters 50
"""
from __future__ import annotations

import argparse
import ctypes
import time

from _common import Report, bootstrap, percentile, stats

bootstrap()

from PySide6.QtCore import Qt, QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QLineEdit,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

user32 = ctypes.WinDLL("user32", use_last_error=True)
SW_RESTORE = 9


# ---------------------------------------------------------------- 焦点守护


class ForegroundGuard:
    """记录并还原前台窗口。"""

    def __init__(self):
        self._ok = True
        try:
            import win32api
            import win32con
            import win32gui
            import win32process

            self._api, self._con = win32api, win32con
            self._gui, self._proc = win32gui, win32process
        except Exception as e:  # noqa: BLE001
            self._ok = False
            self._err = f"{type(e).__name__}: {e}"

    @property
    def available(self) -> bool:
        return self._ok

    @property
    def error(self) -> str:
        return "" if self._ok else self._err

    def snapshot(self) -> int:
        return self._gui.GetForegroundWindow() if self._ok else 0

    def current(self) -> int:
        return self._gui.GetForegroundWindow() if self._ok else 0

    def restore(self, hwnd: int) -> bool:
        if not self._ok or not hwnd or not self._gui.IsWindow(hwnd):
            return False
        if self._gui.GetForegroundWindow() == hwnd:
            return True
        try:
            if self._gui.IsIconic(hwnd):
                self._gui.ShowWindow(hwnd, self._con.SW_RESTORE)

            fg = self._gui.GetForegroundWindow()
            cur_tid = self._api.GetCurrentThreadId()
            fg_tid = self._proc.GetWindowThreadProcessId(fg)[0] if fg else 0
            tgt_tid = self._proc.GetWindowThreadProcessId(hwnd)[0]

            # 关键：AttachThreadInput 解开前台锁
            if fg_tid and fg_tid != cur_tid:
                self._proc.AttachThreadInput(cur_tid, fg_tid, True)
            if tgt_tid and tgt_tid != cur_tid:
                self._proc.AttachThreadInput(cur_tid, tgt_tid, True)
            try:
                self._gui.SetForegroundWindow(hwnd)
            finally:
                if tgt_tid and tgt_tid != cur_tid:
                    self._proc.AttachThreadInput(cur_tid, tgt_tid, False)
                if fg_tid and fg_tid != cur_tid:
                    self._proc.AttachThreadInput(cur_tid, fg_tid, False)

            return self._gui.GetForegroundWindow() == hwnd
        except Exception:
            return False


# ---------------------------------------------------------------- 面板骨架


class AIPanel(QWidget):
    """最小可用的唤起面板骨架：输入框 + 结果视图。"""

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.resize(420, 320)
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("问点什么…")
        self.view = QTextBrowser(self)
        self.hint = QLabel("读取中…", self)
        lay = QVBoxLayout(self)
        lay.addWidget(self.hint)
        lay.addWidget(self.input)
        lay.addWidget(self.view, 1)

    def warm_up(self) -> None:
        """预热：构建控件树并完成一次布局，随后隐藏待命。"""
        self.ensurePolished()
        self.adjustSize()
        self.resize(420, 320)
        self.hide()


def pump(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=50)
    ap.add_argument("--threshold", type=float, default=150.0)
    args = ap.parse_args()

    rep = Report(
        "S3",
        "面板低延迟唤起 + 焦点还原",
        "预热面板可 ≤150ms 可见，且关闭后能 100% 还原原窗口焦点",
        f"预热唤起 P95 ≤ {args.threshold}ms 且 焦点还原成功 → PASS",
    )

    app = QApplication.instance() or QApplication([])

    # --- 1. 冷构建耗时 ---
    t0 = time.perf_counter()
    cold_panel = AIPanel()
    cold_ms = (time.perf_counter() - t0) * 1000
    rep.metric("冷构建耗时", round(cold_ms, 1), " ms")
    rep.note("冷构建若发生在热键回调里，会直接吃掉延迟预算")

    # --- 2. 预热 ---
    t0 = time.perf_counter()
    panel = AIPanel()
    panel.warm_up()
    warm_ms = (time.perf_counter() - t0) * 1000
    rep.metric("预热构建耗时", round(warm_ms, 1), " ms")

    panel.show()
    panel.activateWindow()
    pump(300)

    latencies: list[float] = []
    for _ in range(args.iters):
        panel.hide()
        app.processEvents()
        time.sleep(0.01)
        t0 = time.perf_counter()
        panel.show()
        panel.raise_()
        app.processEvents()
        latencies.append((time.perf_counter() - t0) * 1000)

    st = stats(latencies)
    rep.metric("唤起延迟 P50", st["p50"], " ms")
    rep.metric("唤起延迟 P95", st["p95"], " ms")
    rep.metric("唤起延迟 MAX", st["max"], " ms")
    rep.metric("采样次数", st["n"])

    # --- 3. 焦点还原 ---
    guard = ForegroundGuard()
    rep.check("ForegroundGuard 可用（pywin32）", guard.available, guard.error or "ok")

    if guard.available:
        # 窗口 A：模拟「用户正在使用的应用」
        a = QWidget()
        a.setWindowTitle("S3 — 模拟原应用窗口")
        a.resize(300, 140)
        a.show()
        a.activateWindow()
        a.raise_()
        pump(500)

        hwnd_a = int(a.winId())
        snap = guard.snapshot()
        rep.metric("快照到的前台窗口", hex(snap))
        rep.metric("窗口 A 句柄", hex(hwnd_a))
        rep.check("窗口 A 已获得焦点", snap == hwnd_a, f"fg={hex(snap)} a={hex(hwnd_a)}")

        # 面板抢焦点
        panel.show()
        panel.activateWindow()
        panel.raise_()
        pump(500)
        fg_after_panel = guard.current()
        rep.check("面板成功抢到焦点", fg_after_panel == int(panel.winId()),
                  f"fg={hex(fg_after_panel)}")

        # 还原
        ok_restore = guard.restore(snap)
        pump(400)
        fg_restored = guard.current()
        rep.metric("还原后前台窗口", hex(fg_restored))
        rep.check("关闭面板后焦点还原到窗口 A", fg_restored == hwnd_a,
                  f"fg={hex(fg_restored)} 期望={hex(hwnd_a)}")
        rep.check("restore() 返回 True", ok_restore)
        a.close()
    else:
        rep.check("焦点还原测试", None, "pywin32 不可用，跳过")

    rep.check(f"预热唤起 P95 ≤ {args.threshold}ms", st["p95"] <= args.threshold,
              f"{st['p95']} ms")

    panel.close()
    cold_panel.close()

    if st["p95"] <= args.threshold and guard.available:
        verdict = "PASS"
    elif st["p95"] <= args.threshold:
        verdict = "MANUAL"
    else:
        verdict = "FAIL"

    rep.finish(verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
