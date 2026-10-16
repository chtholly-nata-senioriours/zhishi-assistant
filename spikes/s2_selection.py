#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S2 — 选中文本获取方案是否可用

假设
    「备份剪贴板 → 模拟 Ctrl+C → 读剪贴板 → 还原剪贴板」方案可用，
    且还原是无损的（含富文本格式）。

方法（机制层全自动；真实应用矩阵需人工，见 README）
    1. 剪贴板保真测试：放入「纯文本 + HTML」双格式内容，
       跑一次 get_selected()，校验两种格式都被完整还原。
    2. 真实取值测试：在我们自己的 QTextEdit 里选中一段文字，
       发送合成 Ctrl+C，校验取到的正是选中内容。
    3. 无选中场景：清空选中后调用，校验返回空串且不抛异常。
    4. 空剪贴板场景：校验还原逻辑不崩。

判定
    三项机制测试全部通过 → PASS（真实应用矩阵仍需人工补测）

已知坑
    - 只备份纯文本会导致富文本应用还原时丢格式 —— 必须备份全部 MIME 格式。
    - 管理员权限窗口 / 独占全屏游戏内可能取不到，需人工确认。
    - 剪贴板管理器类软件可能抢占，属外部干扰。

用法
    python spikes/s2_selection.py
"""
from __future__ import annotations

import time

from _common import Report, bootstrap

bootstrap()

from PySide6.QtCore import QByteArray, QMimeData, QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QTextEdit, QWidget  # noqa: E402

CTRL_C_DELAY = 0.18


class SelectionService:
    """选中文本服务（剪贴板方案）。"""

    def __init__(self, delay: float = CTRL_C_DELAY):
        self._clip = QApplication.clipboard()
        self.delay = delay

    # --- 剪贴板备份/还原（全格式）---
    def backup(self) -> dict:
        md = self._clip.mimeData()
        if md is None:
            return {}
        return {fmt: bytes(md.data(fmt)) for fmt in md.formats()}

    def restore(self, data: dict) -> None:
        if not data:
            self._clip.clear()
            return
        md = QMimeData()
        for fmt, raw in data.items():
            md.setData(fmt, QByteArray(raw))
        self._clip.setMimeData(md)

    # --- 取值 ---
    def get_selected(self, timeout_ms: int = 250) -> str:
        backup = self.backup()
        try:
            self._clip.clear()          # 清空以便判断 Ctrl+C 是否真的产生了内容
            self._send_ctrl_c()
            # 必须泵事件循环：目标窗口要能处理 WM_COPY。
            # 用 time.sleep() 会阻塞主线程，导致本进程内的目标窗口收不到按键。
            self._wait(self.delay)
            return self._clip.text() or ""
        finally:
            self.restore(backup)

    @staticmethod
    def _wait(seconds: float) -> None:
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            QApplication.processEvents()
            time.sleep(0.005)

    @staticmethod
    def _send_ctrl_c() -> None:
        from pynput import keyboard as pk

        c = pk.Controller()
        c.press(pk.Key.ctrl_l)
        c.press("c")
        c.release("c")
        c.release(pk.Key.ctrl_l)


def pump(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    rep = Report(
        "S2",
        "选中文本获取方案",
        "备份剪贴板 → Ctrl+C → 读剪贴板 → 还原，机制可用且还原无损",
        "剪贴板保真 + 真实取值 + 边界场景 全部通过 → PASS",
    )

    app = QApplication.instance() or QApplication([])
    svc = SelectionService()
    clip = app.clipboard()

    # --- 1. 剪贴板保真（双格式）---
    src = QMimeData()
    src.setText("CLIPBOARD_SENTINEL_TEXT")
    src.setHtml("<b>CLIPBOARD_SENTINEL_HTML</b>")
    clip.setMimeData(src)
    app.processEvents()
    before = svc.backup()
    rep.metric("备份到的 MIME 格式数", len(before))
    rep.check("备份包含 text/plain", "text/plain" in before)
    rep.check("备份包含 text/html", "text/html" in before)

    # --- 2. 真实取值 ---
    editor = QTextEdit()
    editor.setWindowTitle("S2 选区探针")
    editor.resize(420, 200)
    editor.setPlainText("SELECTION_PROBE_12345")
    editor.show()
    editor.activateWindow()
    editor.raise_()
    pump(500)
    editor.setFocus()
    editor.selectAll()
    pump(200)
    rep.metric("编辑器是否持有焦点", editor.hasFocus())
    rep.metric("应用焦点控件", type(QApplication.focusWidget()).__name__)
    rep.metric("选中字符数", len(editor.textCursor().selectedText()))

    got = svc.get_selected()
    rep.metric("取到的选中文本", repr(got))
    rep.check("成功取到选中文本", got.strip() == "SELECTION_PROBE_12345", repr(got))

    # 还原校验
    app.processEvents()
    after = svc.backup()
    text_ok = clip.text() == "CLIPBOARD_SENTINEL_TEXT"
    html_ok = "CLIPBOARD_SENTINEL_HTML" in (clip.mimeData().html() or "")
    rep.check("纯文本被无损还原", text_ok, repr(clip.text()))
    rep.check("HTML 被无损还原", html_ok)
    rep.check("格式数量未减少", len(after) >= len(before), f"{len(before)} → {len(after)}")

    # --- 3. 无选中场景 ---
    editor.clear()
    editor.setPlainText("")
    pump(150)
    got2 = svc.get_selected()
    rep.check("无选中时返回空串且不抛异常", got2 == "", repr(got2))
    rep.check("无选中后剪贴板仍被还原", clip.text() == "CLIPBOARD_SENTINEL_TEXT")

    # --- 4. 空剪贴板场景 ---
    clip.clear()
    app.processEvents()
    got3 = svc.get_selected()
    rep.check("空剪贴板时不崩", isinstance(got3, str), repr(got3))

    editor.close()

    verdict = "PASS" if all(
        c["ok"] for c in rep.checks if c["ok"] is not None
    ) else "FAIL"

    if verdict == "PASS":
        rep.note("机制层通过；真实应用矩阵（Chrome/VSCode/记事本/Word/微信）需人工补测")

    rep.finish(verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
