# -*- coding: utf-8 -*-
"""S14：常驻指示（托盘进度环）目检 —— P2.14 第 5 步。

为什么必须单独看一眼
    托盘图标的**全部难点在 16×16**：画布上再好看，缩到 16px 也可能糊成一团、
    或者「关闭态」与「0 进度」根本分不出来。规格断言只能证明「三种状态的
    像素不一样」，证明不了「看得出是什么」。

做法
    把三态 × 深浅两套 × 四个真实尺寸（16 / 24 / 32 / 64）画成一张联络表，
    每个尺寸**按 1:1 像素**贴出来（不做任何放大插值）——
    16px 那列就是你实际会在任务栏里看到的样子。

产物：spikes/results/ui_design/tray_states_{light_taskbar,dark_taskbar}.png

用法：python dev_bootstrap.py spikes/s14_tray_indicator.py

为什么按「任务栏底色」而不是「应用主题」分两张
    环的颜色**刻意不随应用主题变**（见 `presentation/tray_icon.py` 里
    `_TRAY_*` 的注释）。托盘画在系统任务栏上，底色由 Windows 决定：
    浅色主题 + 深色任务栏这种组合下，取主题色必然有一半场景糊掉
    （`text_disabled` 会在深色任务栏上直接消失）。所以真正要检查的
    变量是**任务栏底色**，不是应用主题。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRect, Qt                              # noqa: E402
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication                        # noqa: E402

from presentation.design import install, set_theme                # noqa: E402
from presentation.tray_icon import (                              # noqa: E402
    STATE_ACTIVE,
    STATE_DONE,
    STATE_OFF,
    activity_tooltip,
    progress_icon,
)

OUT_DIR = Path(__file__).resolve().parent / "results" / "ui_design"
OUT_DIR.mkdir(parents=True, exist_ok=True)

#: 任务栏实际会用到的尺寸：100% / 125% / 150% DPI，外加一张大图看细节。
SIZES = (16, 24, 32, 64)

#: 两种任务栏底色（Windows 浅色任务栏 / 深色任务栏）。
_TASKBAR = {
    "light_taskbar": "#F3F3F3",
    "dark_taskbar": "#1F1F1F",
}

app = QApplication.instance() or QApplication([])
# 必须先注册，set_theme() 才会真的把 QSS / 字体装上去（S8/S13 都踩过）。
install(app)
set_theme("light", persist=False)


def _cases():
    """(标题, ratio, state, 说明)。三态都要有，外加两个中间进度。"""
    return [
        ("关闭（未采集）", 0.0, STATE_OFF, "灰环 —— 与「0 进度」必须区分开"),
        ("刚开始", 0.06, STATE_ACTIVE, "4 小时目标里的 15 分钟"),
        ("进行中", 0.375, STATE_ACTIVE, "1 小时 30 分 / 4 小时"),
        ("快到了", 0.9, STATE_ACTIVE, "3 小时 36 分 / 4 小时"),
        ("已达成", 1.0, STATE_DONE, "满环换成功色"),
    ]


def _row_height() -> int:
    return 64 + 12


def _build_sheet(taskbar: str) -> QImage:
    base_icon = QIcon(str(Path(__file__).resolve().parent.parent / "图标.ico"))
    cases = _cases()

    width = 520
    header = 26
    row_h = _row_height()
    height = header + row_h * len(cases) + 46

    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(QColor(_TASKBAR[taskbar]))

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    label_font = QFont()
    label_font.setPointSizeF(9.0)
    painter.setFont(label_font)

    # 文字颜色跟着任务栏走，否则浅色任务栏上白字看不见
    ink = "#3C3C3C" if taskbar == "light_taskbar" else "#E8E8E8"
    muted = "#6B7280" if taskbar == "light_taskbar" else "#A0A0A0"

    # 尺寸表头
    x = 150
    for size in SIZES:
        painter.setPen(QColor(muted))
        painter.drawText(QRect(x - 8, 6, 80, 16),
                         Qt.AlignmentFlag.AlignLeft, f"{size}px")
        x += 80

    for row, (title, ratio, state, note) in enumerate(cases):
        y = header + row * row_h
        painter.setPen(QColor(ink))
        painter.drawText(QRect(10, y + 18, 140, 16),
                         Qt.AlignmentFlag.AlignLeft, title)

        icon = progress_icon(ratio, state, base_icon)
        x = 150
        for size in SIZES:
            pm = icon.pixmap(size, size)
            # 1:1 贴出来 —— 放大插值会掩盖「16px 下糊不糊」这个唯一要看的点
            painter.drawPixmap(x, y + (64 - size) // 2, pm)
            x += 80

        # 该状态对应的悬停提示（就是用户真的会看到的那句话）
        painter.setPen(QColor(muted))
        painter.drawText(
            QRect(10, y + 44, width - 20, 16),
            Qt.AlignmentFlag.AlignLeft,
            f"  {note}",
        )

    # 底部：三态判定 + 提示文案
    painter.setPen(QColor(muted))
    painter.drawText(QRect(10, height - 40, width - 20, 16),
                     Qt.AlignmentFlag.AlignLeft,
                     "  activity_state(False, *)=off；ratio>=1 → done；否则 active")
    painter.drawText(
        QRect(10, height - 24, width - 20, 16),
        Qt.AlignmentFlag.AlignLeft,
        "  " + activity_tooltip({"enabled": True, "focus": 5400.0,
                                 "goal": 14400.0, "ratio": 0.375}),
    )
    painter.end()
    return img


def main() -> int:
    for taskbar in ("light_taskbar", "dark_taskbar"):
        path = OUT_DIR / f"tray_states_{taskbar}.png"
        _build_sheet(taskbar).save(str(path))
        print(f"[渲染] {path}")
    print()
    print("RESULT: 已生成托盘三态联络表，请人工目检 16px 那一列")
    return 0


if __name__ == "__main__":
    sys.exit(main())
