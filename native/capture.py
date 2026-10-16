# -*- coding: utf-8 -*-
"""屏幕采集服务。

用 Qt 原生 `QScreen.grabWindow(0)`，零新依赖。
多显示器时把所有屏幕合成到一张「虚拟桌面」画布上，坐标与 `QScreen.geometry()`
一致，避免 DPI 缩放下的错位。
"""
from __future__ import annotations

import base64
from typing import Optional

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap

#: 多模态上传默认使用的编码格式与质量。
#:
#: 为什么默认 JPEG 而不是 PNG（R15 整改，真实屏幕实测）
#:     `to_png_bytes()` 会**同步阻塞主线程**，而这段时间正好落在
#:     「用户框选松手」与「请求发出」之间 —— 手感上就是松手后卡一下。
#:     2560×1600 真实屏幕实测：
#:         PNG  1944 ms / 6212 KB
#:         JPEG   98 ms /  894 KB      → 快 20×、小 7×
#:     1280×800（半分辨率）实测：
#:         PNG   501 ms / 1761 KB
#:         JPEG   23 ms /  306 KB      → 快 22×、小 6×
#:     截图问答并不需要无损与透明通道，JPEG 的编码速度与体积优势是决定性的。
#:     需要无损时显式传 `fmt="PNG"`。
#:
#: ⚠ 注意：不要用「纯色 / 规则网格」的合成图去比体积 —— 那类图对 PNG
#:    极其友好（1920×1080 网格图 PNG 只有 9KB），会得出完全相反的结论。
#:    见 `spikes/s9_perf_tail.py` 的注释。
UPLOAD_FORMAT = "JPEG"
UPLOAD_QUALITY = 88


class CaptureService:
    """屏幕截图。"""

    # ----- 采集 -----

    def virtual_geometry(self) -> QRect:
        """所有屏幕的并集矩形（虚拟桌面坐标）。"""
        screens = QGuiApplication.screens()
        if not screens:
            return QRect()
        union = QRect(screens[0].geometry())
        for s in screens[1:]:
            union = union.united(s.geometry())
        return union

    def grab_fullscreen(self) -> QPixmap:
        """抓取整个虚拟桌面（含所有显示器）。"""
        screens = QGuiApplication.screens()
        if not screens:
            return QPixmap()

        if len(screens) == 1:
            return screens[0].grabWindow(0)

        union = self.virtual_geometry()
        canvas = QPixmap(union.size())
        canvas.fill(QColor(0, 0, 0))
        painter = QPainter(canvas)
        try:
            for s in screens:
                shot = s.grabWindow(0)
                g = s.geometry()
                painter.drawPixmap(g.x() - union.x(), g.y() - union.y(), shot)
        finally:
            painter.end()
        return canvas

    def grab_region(self, x: int, y: int, w: int, h: int) -> QPixmap:
        """按虚拟桌面坐标抓取一块区域。

        性能（M2 实测）
            旧实现「先抓整个屏幕、再 `copy()` 裁剪」：抓 1920×1080 全屏要 **约 90ms**，
            而这 90ms 是**同步阻塞主线程**的 —— 用户框选完松手后会明显顿一下。

            改为直接用 `QScreen.grabWindow()` 的子矩形参数**只抓需要的那块**：
            320×200 的选区降到个位数毫秒。

        跨屏选区仍走合成路径（罕见，且无法避免）。
        """
        region = QRect(x, y, w, h)
        if region.isEmpty():
            return QPixmap()

        screens = QGuiApplication.screens()
        if not screens:
            return QPixmap()

        # 常见情况：选区完整落在某一块屏幕内 → 直接抓子矩形，零合成
        for s in screens:
            g = s.geometry()
            if g.contains(region):
                return s.grabWindow(
                    0,
                    region.x() - g.x(), region.y() - g.y(),
                    region.width(), region.height(),
                )

        # 罕见情况：选区跨屏 → 逐屏抓交集再合成到目标画布
        canvas = QPixmap(region.size())
        canvas.fill(QColor(0, 0, 0))
        painter = QPainter(canvas)
        try:
            for s in screens:
                g = s.geometry()
                inter = g.intersected(region)
                if inter.isEmpty():
                    continue
                shot = s.grabWindow(
                    0,
                    inter.x() - g.x(), inter.y() - g.y(),
                    inter.width(), inter.height(),
                )
                painter.drawPixmap(
                    inter.x() - region.x(), inter.y() - region.y(), shot
                )
        finally:
            painter.end()
        return canvas

    # ----- 导出 -----

    @staticmethod
    def to_png_bytes(pixmap: QPixmap) -> bytes:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buf, "PNG")
        buf.close()
        return bytes(ba)

    @staticmethod
    def to_jpeg_bytes(pixmap: QPixmap, quality: int = UPLOAD_QUALITY) -> bytes:
        """编码为 JPEG（走 `QImage`，可在工作线程调用）。

        JPEG 不支持透明通道 —— 带 alpha 的图直接编码会把透明区变成黑块，
        所以先铺一层白底再画上去。截图本身几乎总是无 alpha 的，
        这一步只为兜住「截到带透明窗口」的少数情况。
        """
        img = pixmap.toImage()
        if img.hasAlphaChannel():
            canvas = QImage(img.size(), QImage.Format.Format_RGB32)
            canvas.fill(QColor(255, 255, 255))
            painter = QPainter(canvas)
            try:
                painter.drawImage(0, 0, img)
            finally:
                painter.end()
            img = canvas

        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "JPEG", quality)
        buf.close()
        return bytes(ba)

    def to_data_url(self, pixmap: QPixmap, fmt: str = UPLOAD_FORMAT,
                    quality: int = UPLOAD_QUALITY) -> str:
        """转为多模态 API 可用的 data URL。

        Args:
            fmt: `"JPEG"`（默认，快且小）或 `"PNG"`（无损）。
            quality: JPEG 质量，仅 `fmt="JPEG"` 时生效。
        """
        if str(fmt).upper() == "PNG":
            raw, mime = self.to_png_bytes(pixmap), "image/png"
        else:
            raw, mime = self.to_jpeg_bytes(pixmap, quality), "image/jpeg"
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"

    @staticmethod
    def save_png(pixmap: QPixmap, path: str) -> bool:
        if pixmap.isNull():
            return False
        return bool(pixmap.save(path, "PNG"))
