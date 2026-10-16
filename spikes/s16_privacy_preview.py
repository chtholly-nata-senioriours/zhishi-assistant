# -*- coding: utf-8 -*-
"""S16：「隐私与数据」页目检（v1.7.0）。

为什么必须单独看一眼
    这一页的每一个字都是**对用户的承诺**（收集什么、不收集什么、存在哪），
    而表格里两个按钮（导出 / 清空）直接作用到磁盘。规格断言能证明
    「行数对、禁用态对」，证明不了「这段话读起来是不是在说人话」
    「空态时按钮该不该是灰的」。所以出图人工确认。

三条渲染前提（沿用 S13 / S15，各踩过一次）
    ① 不设 `QT_QPA_PLATFORM=offscreen` —— 页面上有中文，offscreen 拿不到字形；
    ② 必须先 `install(app)` 再 `set_theme()`；
    ③ 快照前 `show()`，且控件要**挪到屏幕外**（`move(-4000, -4000)`）——
       不然会在用户桌面上闪一下窗口。

数据安全
    预览图里**不许出现用户真实数据**（S8 / S13 同款教训）。本脚本在 import
    任何项目模块之前就把 `PET_DEMO_HOME` 指到一个新建的临时目录，
    并往里**种假数据**（配置 / 会话库 / 活动库 / 日志 / 缓存 / 遗留文件）。

产物：spikes/results/ui_design/
    privacy_light.png / privacy_dark.png      有数据的整页（含左侧导航）
    privacy_empty_light.png                   什么都没有时的样子（按钮全禁用）

用法：python dev_bootstrap.py spikes/s16_privacy_preview.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ============================================================
# 必须在 import 项目模块**之前**把数据根换掉 —— 模块级代码，不是函数。
# config_manager 是进程级单例，import 那一刻就会 _load_config() → save()；
# 晚了就意味着往用户真实的 ~/.pet_demo 里写配置。
# ============================================================
_PREVIEW_HOME = Path(tempfile.mkdtemp(prefix="s16_privacy_home_"))
os.environ["PET_DEMO_HOME"] = str(_PREVIEW_HOME)


def _seed() -> None:
    """种一份**假**的本机数据 —— 页面要能显示出行、大小与可用按钮。"""
    (_PREVIEW_HOME / "logs").mkdir(parents=True, exist_ok=True)
    (_PREVIEW_HOME / "cache" / "icons").mkdir(parents=True, exist_ok=True)

    (_PREVIEW_HOME / "user_config.json").write_text(
        '{\n  "version": "1.7.0",\n  "window": {"center": [1200, 400]},\n'
        '  "ai": {"base_url": "https://api.example.com/v1",\n'
        '          "model": "demo-chat", "api_key": "sk-preview-not-real"}\n}\n',
        encoding="utf-8")
    (_PREVIEW_HOME / "user_config.json.bak-20261014").write_text("{}", encoding="utf-8")

    for stem, table, col, values in (
        ("ai", "sessions", "(id, preset_id, title, created_at, updated_at)",
         "('s1', 'ask', '把这份周报改写成三句话', 1, 1)"),
        ("activity", "segments", "(app, category, start_at, duration_seconds)",
         "('code.exe', 'work', 100, 5400)"),
    ):
        conn = sqlite3.connect(str(_PREVIEW_HOME / f"{stem}.db"))
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {table} {col}")
        conn.execute(f"INSERT OR REPLACE INTO {table} VALUES {values}")
        conn.commit()
        conn.close()

    (_PREVIEW_HOME / "logs" / "app.log").write_text(
        "\n".join(f"2026-10-15 1{i}:00:00 INFO 演示日志第 {i} 行" for i in range(20)),
        encoding="utf-8")
    (_PREVIEW_HOME / "cache" / "icons" / "paw-FFFFFF-24.svg").write_text(
        "<svg/>", encoding="utf-8")
    # 便签 / 快捷启动已随 v1.7.0 移除，这两个文件只作为「遗留数据」出现
    (_PREVIEW_HOME / "notes.json").write_text("[]", encoding="utf-8")
    (_PREVIEW_HOME / "quick_launch.json").write_text("[]", encoding="utf-8")


_seed()

from PySide6.QtGui import QColor, QImage                                # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget                     # noqa: E402

from presentation.design import install, set_theme                      # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "results" / "ui_design"
OUT_DIR.mkdir(parents=True, exist_ok=True)

#: 衬底颜色 —— 与窗口底色拉开，控件的描边 / 圆角 / 留白才看得出来（S13 同款）
_BACKDROP = {"light": "#B9C6DA", "dark": "#3E4859"}

app = QApplication.instance() or QApplication([])
install(app)


def _snap(widget: QWidget, name: str, theme_name: str) -> None:
    widget.move(-4000, -4000)          # 离屏渲染，别在用户桌面上闪窗口
    widget.show()
    app.processEvents()
    app.processEvents()
    img = QImage(widget.size(), QImage.Format.Format_ARGB32)
    img.fill(QColor(_BACKDROP[theme_name]))
    widget.render(img)
    path = OUT_DIR / f"{name}.png"
    img.save(str(path))
    widget.close()
    print(f"[渲染] {path}")


def _snap_page(name: str, theme_name: str, *, height: int = 1000,
               home: Path | None = None) -> None:
    """渲染整页（含左侧导航）。

    `home` 非空时把数据根指过去 —— 空态图要的是一个**干净的新目录**：
    不能删当前目录里的文件（`ai.db` 正被会话历史页的共享单例锁着，
    Windows 上只会得到 WinError 32），也不该让哪一页读到用户真实数据。
    """
    if home is not None:
        from engine.ai.store import close_shared_store

        close_shared_store()
        os.environ["PET_DEMO_HOME"] = str(home)

    from presentation.control_center import ControlCenter, reset_instance

    reset_instance()
    cc = ControlCenter(app=None)
    cc.resize(1060, height)
    cc.goto("隐私与数据")
    _snap(cc, name, theme_name)


def main() -> int:
    for theme_name in ("light", "dark"):
        set_theme(theme_name, persist=False)
        _snap_page(f"privacy_{theme_name}", theme_name)

    # 空态：换一个全新的空目录（见 `_snap_page` 的说明）
    empty_home = Path(tempfile.mkdtemp(prefix="s16_privacy_empty_"))
    set_theme("light", persist=False)
    _snap_page("privacy_empty_light", "light", home=empty_home)

    print()
    print("RESULT: 请人工确认")
    print("  1. 承诺卡的文字读起来像人话，且每一句与实现对得上")
    print("  2. 表格每行两个按钮（导出 / 清空），行高够不挤")
    print("  3. 空态图里按钮是**铺平的**（没有填充底、文字更淡）—— 实测禁用态")
    print("     与可用态逐像素 100% 不同，不会看成「点了没反应」；大小列显示「—」")
    print("  4. 左导航新增「隐私与数据」并带盾牌图标")
    return 0


if __name__ == "__main__":
    sys.exit(main())
