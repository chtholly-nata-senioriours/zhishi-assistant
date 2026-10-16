# -*- coding: utf-8 -*-
"""性能收尾的回归测试（R14 选区采集 / R15 截图编码）。

守的是两条**可观测的行为契约**，而不是某个具体毫秒数：

    R14  发完 Ctrl+C 后，剪贴板一有内容就应立刻返回 ——
         而不是无条件等满 timeout。没有选中文本时仍要等满 timeout 再返回空串，
         并且**剪贴板必须被还原**。
    R15  多模态上传默认走 JPEG；PNG 路径仍然可用；带 alpha 的图不会出黑块。

运行:
    python tests/test_perf_tail.py
    pytest tests/test_perf_tail.py -v
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import pytest

from native.capture import CaptureService
from native.selection import POLL_INTERVAL, SelectionService, clipboard_sequence

# ============================================================
# R14 —— 选区采集
# ============================================================


class _Target(SelectionService):
    """假目标应用：收到 Ctrl+C 后延迟 `delay_ms` 才把内容写进剪贴板。

    同时要模拟「剪贴板发生了一次新的复制」。真实环境靠
    `GetClipboardSequenceNumber()` 观测，但单元测试跑在 `offscreen` 平台下，
    Qt 用的是**进程内**剪贴板，序列号不会动，所以这里用自增计数代替 ——
    语义与真实一致：写入内容 ⇒ 版本 +1（先写内容，再抬版本）。
    """

    def __init__(self, delay_ms: int, text: str = "选中的文字"):
        super().__init__()
        self.delay_ms = delay_ms
        self.text = text
        self._version = 0

    def _clip_token(self) -> int:
        return self._version

    def _send_copy(self) -> None:
        def _write() -> None:
            self.set_clipboard(self.text)
            self._version += 1

        QTimer.singleShot(self.delay_ms, _write)


def test_get_selected_returns_as_soon_as_content_appears():
    """内容 20ms 就绪 → 不该等满 250ms。"""
    svc = _Target(20)
    t0 = time.perf_counter()
    got = svc.get_selected(timeout_ms=250)
    dt = (time.perf_counter() - t0) * 1000

    assert got == "选中的文字"
    # 旧实现固定等 250ms；这里留足余量但必须明显更短。
    assert dt < 150, f"应当在内容就绪后立即返回，实测 {dt:.0f}ms"


def test_get_selected_poll_interval_is_small():
    """轮询间隔必须远小于 timeout，否则省下来的延迟又被轮询粒度吃掉。"""
    assert 0 < POLL_INTERVAL <= 0.02


def test_get_selected_times_out_when_nothing_selected():
    """没有选中文本 → 等满 timeout 后返回空串（不能提前返回假结果）。"""
    svc = _Target(10_000)          # 永远不写剪贴板
    t0 = time.perf_counter()
    got = svc.get_selected(timeout_ms=120)
    dt = (time.perf_counter() - t0) * 1000

    assert got == ""
    assert dt >= 100, f"应当等满 timeout，实测 {dt:.0f}ms"
    assert dt < 900, f"超时不该失控，实测 {dt:.0f}ms"


def test_get_selected_restores_clipboard():
    """取完选中文本后，用户原来的剪贴板内容必须原样回来。"""
    clip = QApplication.clipboard()
    clip.setText("用户原来的内容")

    svc = _Target(15)
    assert svc.get_selected(timeout_ms=250) == "选中的文字"
    assert clip.text() == "用户原来的内容"


def test_get_selected_handles_empty_target():
    """目标应用不响应（例如无焦点）时不抛异常，返回空串。"""
    class _Mute(SelectionService):
        def _clip_token(self) -> int:
            return 0            # 版本恒定 —— 相当于没有任何新复制

        def _send_copy(self) -> None:
            pass

    svc = _Mute()
    assert svc.get_selected(timeout_ms=60) == ""


def test_clipboard_sequence_moves_on_real_copy():
    """序列号判据本身：真实剪贴板变化一次，序列号必须 +1。

    这是 R14 第二半（不再 `clear()`）的地基。offscreen 平台下 Qt 用进程内
    剪贴板、不触碰 Windows 剪贴板，因此这里**跳过**；
    用 `QT_QPA_PLATFORM=windows` 跑本文件时会真正执行。
    剪贴板按全 MIME 备份、跑完原样还原，不污染用户剪贴板。
    """
    if app.platformName() != "windows":
        pytest.skip("需要真实 Windows 剪贴板（QT_QPA_PLATFORM=windows）")

    svc = SelectionService()
    backup = svc.backup()
    try:
        s0 = clipboard_sequence()
        svc.set_clipboard("seq-probe-A")
        s1 = clipboard_sequence()
        svc.set_clipboard("seq-probe-B")
        s2 = clipboard_sequence()
        assert s0 >= 0, "Windows 上序列号 API 必须可用"
        assert s1 != s0 and s2 != s1, f"剪贴板变化后序列号应递增：{s0}→{s1}→{s2}"
    finally:
        svc.restore(backup)


# ============================================================
# R15 —— 截图编码
# ============================================================

def _pixmap(w: int = 320, h: int = 200) -> QPixmap:
    pm = QPixmap(w, h)
    pm.fill(QColor(28, 30, 44))
    return pm


def test_jpeg_encoding_produces_valid_jpeg():
    raw = CaptureService().to_jpeg_bytes(_pixmap())
    assert raw[:2] == b"\xff\xd8", "JPEG 必须以 SOI 标记开头"
    assert len(raw) > 100


def test_data_url_defaults_to_jpeg():
    url = CaptureService().to_data_url(_pixmap())
    assert url.startswith("data:image/jpeg;base64,")


def test_data_url_can_force_png():
    url = CaptureService().to_data_url(_pixmap(), fmt="PNG")
    assert url.startswith("data:image/png;base64,")


def test_png_path_still_available():
    raw = CaptureService().to_png_bytes(_pixmap())
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_jpeg_flattens_alpha_instead_of_black_blocks():
    """带 alpha 的图直接编码会把透明区变黑块 —— 必须先铺白底。"""
    img = QImage(64, 64, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    raw = CaptureService().to_jpeg_bytes(QPixmap.fromImage(img))

    back = QImage.fromData(raw, "JPEG")
    assert not back.isNull()
    assert back.pixelColor(32, 32).lightness() > 200, "透明区应当被铺成白底"


def test_jpeg_is_faster_than_png_on_realistic_content():
    """编码速度是 R15 的核心收益，不能退化。"""
    from PySide6.QtGui import QLinearGradient, QPainter

    pm = QPixmap(1280, 800)
    p = QPainter(pm)
    try:
        grad = QLinearGradient(0, 0, 1280, 800)
        grad.setColorAt(0.0, QColor(20, 20, 40))
        grad.setColorAt(1.0, QColor(90, 110, 170))
        p.fillRect(0, 0, 1280, 800, grad)
        p.setPen(QColor(230, 230, 230))
        for i in range(0, 1280, 7):
            p.drawLine(i, 0, i, 800)
    finally:
        p.end()

    svc = CaptureService()
    t0 = time.perf_counter()
    svc.to_png_bytes(pm)
    t_png = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    svc.to_jpeg_bytes(pm)
    t_jpg = (time.perf_counter() - t0) * 1000

    assert t_jpg < t_png, f"JPEG 应当快于 PNG（jpeg {t_jpg:.1f}ms / png {t_png:.1f}ms）"


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
