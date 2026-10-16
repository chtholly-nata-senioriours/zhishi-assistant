# -*- coding: utf-8 -*-
"""S15：悬浮球外观目检 —— P2.16 第 1 步。

为什么必须单独看一眼
    球是**自绘**的（`paintEvent` 全是 QPainter），规格断言只能证明
    「四种状态的像素不一样」「环的像素随比例增加」，证明不了
    「在真实壁纸上还看得出是什么」。而球的底色恰恰是**壁纸** ——
    比托盘那条任务栏更不可预测（任务栏至少只有深浅两种）。

    所以真正要检查的变量是**壁纸底色**，不是应用主题。
    这与 S14 的结论同源（见 `spikes/README.md`「S14 结果」）：
    **判据：这个图标的背景由谁决定？不是应用就別问主题。**

做法
    每个壁纸底色一张图，图里并排：
      · 五态（常态 / 专注中 / 已达成 / 休眠 / 未采集）各 1:1 与 3 倍放大
      · 悬停（1.08 倍）与被戳脉冲（1.18 倍）两种瞬时态
    另外两张气泡图**按应用主题**分（气泡走全局 QSS，底色是应用给的），
    一张贴边图看「1/3 藏在屏幕外」的实际观感。

产物：spikes/results/ui_design/orb_on_wallpaper_<底色>.png
      spikes/results/ui_design/orb_bubble_<主题>.png
      spikes/results/ui_design/orb_edge_snap.png

用法：python dev_bootstrap.py spikes/s15_orb_preview.py

三条硬前提（各踩过一次，见 spikes/README.md）
    ① 不设 `QT_QPA_PLATFORM=offscreen` —— 气泡里有中文，offscreen 拿不到中文字形；
    ② 先 `install(app)` 再 `set_theme()` —— 不注册的话等于什么都没装；
    ③ 快照前要 `show()` —— QSS 背景在 polish 阶段才套上。
    球本身没有文字，但气泡有，所以整脚本一律走真实平台。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt          # noqa: E402
from PySide6.QtGui import (                                            # noqa: E402
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QRegion,
)
from PySide6.QtWidgets import QApplication, QWidget                    # noqa: E402

from presentation.bubble import Bubble                                 # noqa: E402
from presentation.design import install, set_theme                     # noqa: E402
from presentation.forms import OrbForm                                  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "results" / "ui_design"
OUT_DIR.mkdir(parents=True, exist_ok=True)

#: 四张代表壁纸。前三个是纯色（深浅灰），第四个是**渐变 + 花纹** ——
#: 纯色壁纸只能证明「对比度够」，证明不了「有内容时还看得清」。
WALLPAPERS = {
    "deep": ("深色壁纸", "#141414"),
    "mid": ("中灰壁纸", "#7A7A7A"),
    "light": ("浅色壁纸", "#EDEDED"),
    "busy": ("花哨壁纸（渐变+形状）", None),
}

#: 五态 + 两个专注计时态（P2.18）。`ratio` 用**非等距**的取值 —— 等距会让
#: 「按比例画」与「固定画几段」结果相同，目检就分不出来了（P2.14 踩过）。
#:
#: 专注那两行刻意让「今日 75% / 本次 37.5%」**方向相反且不成倍数** ——
#: 两个数都取 0.5 的话，把口径接反了目检也看不出来。
STATES = [
    ("常态", "idle", 0.0, True, None),
    ("专注中", "focus", 0.375, True, None),
    ("已达成", "idle", 1.0, True, None),
    ("休眠", "sleep", 0.0, True, None),
    ("未采集", "idle", 0.0, False, None),
    ("专注计时中", "idle", 0.75, True, (0.375, False)),
    ("专注已暂停", "idle", 0.75, True, (0.375, True)),
]

app = QApplication.instance() or QApplication([])
install(app)                       # 前提②：必须先注册
set_theme("light", persist=False)


# ---------------------------------------------------------------- 工具


def render_form(form: QWidget) -> QImage:
    """把控件画进一张**带透明背景**的图。

    不能用 `grab()` —— 它默认带 `DrawWindowBackground`，会把未绘制区域
    填成不透明，于是「球外面应该是透明的」这件事根本量不出来。
    """
    img = QImage(form.size(), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    form.render(p, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
    p.end()
    return img


def make_orb(state: str, ratio: float, enabled: bool, focus=None) -> OrbForm:
    form = OrbForm(size=52)
    form.set_state(state)
    form.set_progress(ratio, enabled)
    if focus is not None:
        form.set_focus(focus[0], paused=focus[1])
    return form


def paint_wallpaper(p: QPainter, rect: QRect, tone: str) -> None:
    """把一块壁纸铺进 rect。`busy` 用渐变 + 圆斑模拟真实照片。"""
    if tone == "busy":
        grad = QLinearGradient(QPointF(rect.topLeft()), QPointF(rect.bottomRight()))
        grad.setColorAt(0.0, QColor("#2B3A67"))
        grad.setColorAt(0.5, QColor("#7B4B94"))
        grad.setColorAt(1.0, QColor("#C46D5E"))
        p.fillRect(rect, grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 46))
        p.drawEllipse(QPointF(rect.left() + rect.width() * 0.24,
                              rect.top() + rect.height() * 0.3), 46, 46)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QPointF(rect.left() + rect.width() * 0.78,
                              rect.top() + rect.height() * 0.74), 64, 40)
    else:
        p.fillRect(rect, QColor(WALLPAPERS[tone][1]))


def ink_for(tone: str) -> tuple[str, str]:
    """该壁纸上的文字色 / 次要文字色。深壁纸配浅字，反之亦然。"""
    if tone in ("deep", "busy"):
        return "#F2F2F2", "#B9B9B9"
    return "#2B2B2B", "#6B6B6B"


# ---------------------------------------------------------------- 图 1：五态 × 壁纸


def build_wallpaper_sheet(tone: str) -> QImage:
    scale = 3
    cell = 64 * scale
    pad = 14
    label_w = 132
    width = label_w + pad + (cell + pad) * 2 + 210
    row_h = cell + pad + 26
    header = 30
    # 末尾还要放一行「瞬时态」（64px 球 + 说明文字）——
    # 之前只留 40px，那一行整个被裁在画布外（目检时才发现）。
    height = header + row_h * len(STATES) + 130

    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    title, _ = WALLPAPERS[tone]
    font = QFont()
    font.setPointSizeF(10.0)
    p.setFont(font)
    p.setPen(QColor("#2B2B2B"))
    p.drawText(QRect(12, 4, width - 24, 22), Qt.AlignmentFlag.AlignLeft,
               f"S15 悬浮球 · {title} · 1:1 与 {scale}× 放大")

    ink, muted = ink_for(tone)
    small = QFont()
    small.setPointSizeF(8.5)

    for row, (label, state, ratio, enabled, focus) in enumerate(STATES):
        y = header + row * row_h

        # 这一行左侧的说明
        p.setFont(font)
        p.setPen(QColor("#2B2B2B"))
        p.drawText(QRect(12, y + cell // 2 - 12, label_w, 20),
                   Qt.AlignmentFlag.AlignLeft, label)

        orb = make_orb(state, ratio, enabled, focus)
        rendered = render_form(orb)
        ratio_now, ring = orb.progress()

        x = label_w + pad
        for factor in (1, scale):
            box = 64 * factor
            band = QRect(x, y, box, box)
            paint_wallpaper(p, band, tone)
            p.setPen(QColor("#C8C8C8"))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(band.adjusted(0, 0, -1, -1))
            p.drawImage(x, y, rendered.scaled(box, box,
                                              Qt.AspectRatioMode.IgnoreAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
            x += box + pad

        # 右侧读数 —— 目检图里也要能核对「这一格画的是不是我要的状态」
        p.setFont(small)
        p.setPen(QColor(muted))
        p.drawText(QRect(x + 6, y + 8, 200, 18), Qt.AlignmentFlag.AlignLeft,
                   f"state={state}  环值={ratio_now:.3f}"
                   + (f"  focus={focus[0]:.3f}" if focus else ""))
        p.drawText(QRect(x + 6, y + 28, 200, 18), Qt.AlignmentFlag.AlignLeft,
                   f"环状态={ring}")
        center = rendered.pixelColor(rendered.width() // 2, rendered.height() // 2)
        p.drawText(QRect(x + 6, y + 48, 200, 18), Qt.AlignmentFlag.AlignLeft,
                   f"中心像素={center.name()} a={center.alpha()}")
        corner = rendered.pixelColor(1, 1)
        p.drawText(QRect(x + 6, y + 68, 200, 18), Qt.AlignmentFlag.AlignLeft,
                   f"角落 alpha={corner.alpha()}（应为 0=透明）")

    # 底部：瞬时态
    y = header + row_h * len(STATES) + 4
    p.setFont(font)
    p.setPen(QColor("#2B2B2B"))
    p.drawText(QRect(12, y, 200, 20), Qt.AlignmentFlag.AlignLeft,
               "瞬时态（1:1）：")
    x = label_w + pad
    for caption, hover, pulse in (("悬停 1.08×", True, 1.0), ("被戳 1.18×", False, 1.18)):
        orb = make_orb("idle", 0.375, True)
        orb._hover = hover
        orb._pulse = pulse
        rendered = render_form(orb)
        band = QRect(x, y, 64, 64)
        paint_wallpaper(p, band, tone)
        p.setPen(QColor("#C8C8C8"))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(band.adjusted(0, 0, -1, -1))
        p.drawImage(x, y, rendered)
        p.setFont(small)
        p.setPen(QColor(muted))
        p.drawText(QRect(x, y + 66, 160, 16), Qt.AlignmentFlag.AlignLeft, caption)
        x += 64 + pad
    p.end()
    return img


# ---------------------------------------------------------------- 图 2：气泡


def build_bubble_sheet(theme: str) -> QImage:
    set_theme(theme, persist=False)

    text = "今天已经专注 1 小时 30 分，进度 37%，继续加油！"
    bubble = Bubble()
    anchor = QWidget()                       # 只为满足签名，摆位稍后手动改
    bubble.show_text(text, anchor, duration_ms=600_000)
    app.processEvents()
    bubble.move(QPoint(0, 0))                # 脱离真实屏幕坐标，便于合成
    app.processEvents()
    shot = bubble.grab().toImage()      # grab() 给的是 QPixmap，drawImage 要 QImage
    bubble.hide()

    width = 560
    height = 420
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    font = QFont()
    font.setPointSizeF(10.0)
    p.setFont(font)
    p.setPen(QColor("#2B2B2B"))
    p.drawText(QRect(12, 4, width - 24, 22), Qt.AlignmentFlag.AlignLeft,
               f"S15 气泡 · 应用主题 {theme} · 真实控件 grab()")

    # 上下两块壁纸，各贴一次气泡：上面演示「球在下方」，下面演示「翻到下方」
    for index, (tone, caption) in enumerate((("deep", "深色壁纸"), ("light", "浅色壁纸"))):
        top = 34 + index * 190
        band = QRect(12, top, width - 24, 180)
        paint_wallpaper(p, band, tone)
        p.setPen(QColor("#C8C8C8"))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(band.adjusted(0, 0, -1, -1))

        ink, _ = ink_for(tone)
        p.setPen(QColor(ink))
        p.drawText(QRect(band.left() + 8, band.top() + 6, 300, 18),
                   Qt.AlignmentFlag.AlignLeft, caption)

        orb = make_orb("idle", 0.375, True)
        orb_img = render_form(orb)
        cx = band.center().x()

        if index == 0:
            # 气泡在上、球在下（正常情形）
            bx = cx - shot.width() // 2
            by = band.top() + 30
            p.drawImage(bx, by, shot)
            p.drawImage(cx - 32, by + shot.height() + 8, orb_img)
        else:
            # 球在上、气泡翻到下方（贴着屏幕上沿时的兜底）
            oy = band.top() + 22
            p.drawImage(cx - 32, oy, orb_img)
            p.drawImage(cx - shot.width() // 2, oy + 72, shot)
    p.end()
    return img


# ---------------------------------------------------------------- 图 3：贴边


def build_edge_sheet() -> QImage:
    # 四格：左吸 / 右吸 / 展开 / 桌宠对比。宽 = 12 + 4×(200+12)，少一格就会
    # 静默漏掉最后那张对比图（之前写 720，桌宠那格根本没画出来）。
    width, height = 12 + 4 * (200 + 12), 300
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    font = QFont()
    font.setPointSizeF(10.0)
    p.setFont(font)
    p.setPen(QColor("#2B2B2B"))
    p.drawText(QRect(12, 4, width - 24, 22), Qt.AlignmentFlag.AlignLeft,
               "S15 贴边吸附 · 左边（藏 1/3） / 右边（藏 1/3） / 鼠标移上去完全拉出")

    inset = OrbForm(size=52).edge_snap_inset()
    small = QFont()
    small.setPointSizeF(8.5)

    # 三段并排：左吸 / 右吸 / 展开
    panels = [("左吸：藏 1/3 在屏幕外", "left"), ("右吸：藏 1/3 在屏幕外", "right"),
              ("鼠标移上去 → 完全拉出", "expand")]
    panel_w = 200
    for index, (caption, mode) in enumerate(panels):
        left = 12 + index * (panel_w + 12)
        top = 34
        screen = QRect(left, top, panel_w, 180)
        paint_wallpaper(p, screen, "busy")
        p.setPen(QColor("#C8C8C8"))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(screen.adjusted(0, 0, -1, -1))

        orb_img = render_form(make_orb("focus", 0.375, True))
        if mode == "left":
            x, y = screen.left() - inset, screen.center().y() - 32
        elif mode == "right":
            x, y = screen.right() - 64 + inset + 1, screen.center().y() - 32
        else:
            x, y = screen.center().x() - 32, screen.center().y() - 32

        # 裁剪到屏幕区域 —— 模拟「屏幕外那部分看不见」
        p.save()
        p.setClipRect(screen)
        p.drawImage(x, y, orb_img)
        p.restore()

        p.setFont(small)
        p.setPen(QColor("#6B6B6B"))
        p.drawText(QRect(left, top + 186, panel_w, 32),
                   Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, caption)

    p.setFont(small)
    p.setPen(QColor("#6B6B6B"))
    p.drawText(QRect(12, height - 26, width - 24, 18), Qt.AlignmentFlag.AlignLeft,
               f"edge_snap_inset() = {inset}px（画布 64px 的 1/3）；垂直方向夹在 availableGeometry() 内")
    p.end()
    return img


# ---------------------------------------------------------------- main


def main() -> int:
    for tone in WALLPAPERS:
        path = OUT_DIR / f"orb_on_wallpaper_{tone}.png"
        build_wallpaper_sheet(tone).save(str(path))
        print(f"[渲染] {path}")

    for theme in ("light", "dark"):
        path = OUT_DIR / f"orb_bubble_{theme}.png"
        build_bubble_sheet(theme).save(str(path))
        print(f"[渲染] {path}")

    path = OUT_DIR / "orb_edge_snap.png"
    build_edge_sheet().save(str(path))
    print(f"[渲染] {path}")

    set_theme("light", persist=False)
    print()
    print("RESULT: 已生成悬浮球目检图，请人工确认：")
    print("  1. 五态在四种壁纸上都分得清（尤其深色壁纸上的『休眠』与『未采集』）")
    print("  2. 环的起点在 12 点、顺时针、按比例（37.5% 要明显不是 1/3 整）")
    print("  3. 球外一圈是全透明（角落 alpha=0）")
    print("  4. 气泡中文不是豆腐块，且两种壁纸上都读得清")
    return 0


if __name__ == "__main__":
    sys.exit(main())
