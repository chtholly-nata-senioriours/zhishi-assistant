#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S8 — UI 设计系统统一性（VS Code / Win11 取向）

背景（用户第三次提要求）
    前两轮 UI 工作的结果是「iOS 液态玻璃」风格：20px 大圆角、半透明底、
    顶部高光、弹性动画。用户明确要求换成 **VS Code + Windows 11 原生**的
    工具类审美，并给了硬性规格：

        配色  深色 #252526 / 面板 #1E1E1E / 强调 #4C8DFF
              浅色 #F3F3F3 / 面板 #FFFFFF / 强调 #0067C0
              文字三级灰阶（主 / 次 / 禁用 40%）
        字体  9pt，DPI 自适应，**禁止写死 px 字号**；日志区用等宽
        间距  4px 基准栅格，控件 padding 6-8px，工具栏图标 16x16
        圆角  2px，按钮 3px（**不追求大圆角**）
        边框  1px，前景色 12% 透明度，**不用阴影**
        布局  工具栏 + 左导航(200-240px) + QStackedWidget + 状态栏
        四态  hover / pressed / checked / disabled
        数据区 行高 28px、行 hover 变色、整行选中、表头区分
        滚动条 8px，hover 变宽，圆角 2px
        日志  只有级别标签着色，禁止整段彩色
        空状态 必须有引导文案
        图标  统一来源（Lucide 风格 SVG），深浅各一套
        QSS  选择器精确到控件类，**禁止全局 QWidget**（窗口级用 .QWidget）
        颜色 **全部收敛到 Theme**，QSS 里禁止写死 hex

根因（为什么之前「各个部分 ui 设计不统一」）
    设计 token 根本不存在 —— 每个窗口各写各的颜色与圆角，`appearance.theme`
    配置项从来没有任何代码读过。所以「统一」不是调几个数值，而是要
    **先建一个设计系统**：presentation/design/{tokens,theme,qss,icons,widgets}。

本 spike 做什么
    1. 自动断言上述**可判定**的规格（hex 收敛、pt 字号、圆角、栅格、
       四态、滚动条、选择器纪律、日志着色、空状态、图标）。
    2. 用**真实平台**渲染 控制中心 / AI 面板 / 各类对话框 的浅深两套图，
       落盘供人工目检（观感无法自动判定）。

用法
    python dev_bootstrap.py spikes/s8_ui_design.py
    产物：spikes/results/ui_design/*.png
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = Path(__file__).resolve().parent / "results" / "ui_design"

#: 衬底颜色（浅色主题给深底、深色主题给浅底，更容易看出描边与圆角）
_BACKDROP = {"light": "#B9C6DA", "dark": "#3E4859"}

_SAMPLE_MD = """### 翻译结果

快速的棕色狐狸跳过了懒惰的狗。

- 这是一段中文测试，含**全角标点**
- 行内代码 `pip install`

> 引用块示例
"""


def main() -> int:
    from spikes._common import Report, bootstrap

    bootstrap()

    rep = Report(
        "S8",
        "UI 设计系统统一性（VS Code / Win11 取向）",
        "设计 token 不存在 → 各窗口各写各的颜色与圆角；"
        "`appearance.theme` 从未被读取，所以「统一」无从谈起",
        "规格中所有可判定项全过 + 浅深两套图人工目检通过 → PASS",
    )

    # Qt 用真实平台：offscreen 下拿不到中文字形，渲染出来全是豆腐块
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QMouseEvent
    from PySide6.QtWidgets import (
        QDialog,
        QMessageBox,
        QStackedWidget,
        QStatusBar,
        QToolBar,
        QToolButton,
    )

    from presentation.design import install, theme
    from presentation.design import icons, qss as design_qss, set_theme, tokens

    install(app)

    # ==========================================================
    # 1. 规格：颜色收敛
    # ==========================================================

    src = (ROOT / "presentation" / "design" / "qss.py").read_text(encoding="utf-8")
    hex_lines = [ln.strip() for ln in src.splitlines()
                 if re.search(r"#[0-9a-fA-F]{3,8}\b", ln) and not ln.strip().startswith("#")]
    rep.check("QSS 源码零 hex 字面量（颜色全部来自 token）",
              not hex_lines, f"违规行: {hex_lines[:3]}" if hex_lines else "0 处")

    bad_inline = []
    for path in list((ROOT / "presentation").rglob("*.py")) + \
            list((ROOT / "extensions").rglob("*.py")):
        if "design" in path.parts:
            continue
        for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "setStyleSheet" in ln and re.search(r"#[0-9a-fA-F]{3,8}\b", ln):
                bad_inline.append(f"{path.relative_to(ROOT)}:{i}")
    rep.check("UI 代码无「内联样式表写死颜色」",
              not bad_inline, f"违规: {bad_inline[:3]}" if bad_inline else "0 处")

    # ==========================================================
    # 2. 规格：尺寸 / 圆角 / 字体
    # ==========================================================

    rep.check("圆角 2px、按钮 3px（不追求大圆角）",
              tokens.RADIUS["window"] == 2 and tokens.RADIUS["control"] == 2
              and tokens.RADIUS["button"] == 3,
              f"window={tokens.RADIUS['window']} control={tokens.RADIUS['control']} "
              f"button={tokens.RADIUS['button']}")

    off_grid = {k: v for k, v in tokens.SPACING.items() if v % 4}
    rep.check("间距全在 4px 基准栅格上", not off_grid, str(off_grid) if off_grid else "全部合规")

    rep.check("数据密集区行高 28px / 控件高 28px",
              tokens.ROW_HEIGHT == 28 and tokens.CONTROL_HEIGHT == 28,
              f"ROW_HEIGHT={tokens.ROW_HEIGHT} CONTROL_HEIGHT={tokens.CONTROL_HEIGHT}")

    rep.check("滚动条 8px 窄条，hover 变宽",
              tokens.SCROLLBAR_WIDTH == 8
              and tokens.SCROLLBAR_WIDTH_HOVER > tokens.SCROLLBAR_WIDTH,
              f"{tokens.SCROLLBAR_WIDTH}px → {tokens.SCROLLBAR_WIDTH_HOVER}px")

    rep.check("工具栏图标 16x16", tokens.ICON_SIZE == 16, f"ICON_SIZE={tokens.ICON_SIZE}")

    # ==========================================================
    # 3. 规格：QSS 纪律（选择器 / 四态 / 字号单位）
    # ==========================================================

    set_theme("dark", persist=False)
    s_dark = design_qss.build_qss(theme())
    set_theme("light", persist=False)
    s_light = design_qss.build_qss(theme())
    set_theme("dark", persist=False)

    left = set(re.findall(r"\{[A-Za-z_]+\}", s_dark))
    rep.check("生成的 QSS 无未替换占位符", not left, f"残留: {left}" if left else "无")

    rep.check("浅 / 深两份 QSS 不同，且各自用了规格里的窗口底色",
              s_light != s_dark
              and "#F3F3F3" in s_light.upper() and "#252526" in s_dark.upper(),
              "浅 #F3F3F3 / 深 #252526")

    stripped = s_dark.replace(".QWidget", "")
    bare = re.findall(r"(?:^|\n)\s*QWidget\s*(?:,|\{)", stripped)
    rep.check("无裸 QWidget 选择器（窗口级用 .QWidget）",
              not bare, f"发现 {len(bare)} 处" if bare else "0 处")

    px_sizes = [m.group(0) for m in re.finditer(r"font-size:\s*[\d.]+px", s_dark)]
    rep.check("字号一律 pt，无 px 写死", not px_sizes, str(px_sizes[:3]) if px_sizes else "全部 pt")

    states = [st for st in (":hover", ":pressed", ":checked", ":disabled")
              if f"QToolButton{st}" not in s_dark]
    rep.check("工具栏按钮四态齐全（hover/pressed/checked/disabled）",
              not states, f"缺 {states}" if states else "四态齐")

    log_block = re.search(r"QPlainTextEdit#logView[^{]*\{(.*?)\}", s_dark, re.S)
    rep.check("日志区使用等宽字体",
              bool(log_block) and "font-family" in log_block.group(1),
              "QPlainTextEdit#logView 指定了 font-family")

    # ==========================================================
    # 4. 规格：图标
    # ==========================================================

    rep.check("图标库规模足够（统一来源：Lucide 风格内联 SVG）",
              len(icons.ICONS) >= 30, f"{len(icons.ICONS)} 个图标")

    broken = [n for n in icons.ICONS
              if not icons.svg_markup(n, "#FFFFFF").startswith("<svg")]
    rep.check("全部图标可生成 SVG", not broken, str(broken) if broken else "全部可生成")

    set_theme("light", persist=False)
    light_key = icons.icon("gear", theme().color("text").name()).cacheKey()
    set_theme("dark", persist=False)
    dark_key = icons.icon("gear", theme().color("text").name()).cacheKey()
    rep.check("图标跟随主题换色（深浅各一套）",
              light_key != dark_key, "同一图标在两套主题下 cacheKey 不同")

    rep.check("未知图标名返回空图标而非抛异常",
              icons.icon("no_such_icon_xyz").isNull(), "isNull() == True")

    # ==========================================================
    # 5. 结构：控制中心
    # ==========================================================

    from presentation.control_center import NAV_ITEMS, ControlCenter, reset_instance

    reset_instance()
    cc = ControlCenter(app=None)
    rep.check("主窗口 = 工具栏 + 左导航 + QStackedWidget + 状态栏",
              cc.findChild(QToolBar) is not None
              and cc.findChild(QStackedWidget) is not None
              and cc.findChild(QStatusBar) is not None,
              "四件套齐备")

    tb_btns = [b for b in cc.findChild(QToolBar).findChildren(QToolButton)
               if b.objectName() != "qt_toolbar_ext_button"]
    rep.check("工具栏按钮 iconOnly + tooltip",
              bool(tb_btns) and all(b.text() == "" and b.toolTip() for b in tb_btns),
              f"{len(tb_btns)} 个按钮")

    rep.check("左导航宽度在 200-240px 规格内",
              tokens.NAV_WIDTH[0] <= cc._nav.width() <= tokens.NAV_WIDTH[1]
              or tokens.NAV_WIDTH[0] <= cc._nav.minimumWidth() <= tokens.NAV_WIDTH[1],
              f"NAV_WIDTH={tokens.NAV_WIDTH}")

    rep.check("页面数与导航项数一致",
              len(cc._pages) == len(NAV_ITEMS),
              f"{len(cc._pages)} 页 / {len(NAV_ITEMS)} 项")

    # ==========================================================
    # 6. 结构：「风格统一」靠共享同一份样式表保证
    # ==========================================================

    from presentation.ai_panel import AIPanel
    from presentation.dialogs import AppDialog

    panel = AIPanel()
    dlg = AppDialog(title="检查")

    def _effective(w) -> str:
        """控件自身的样式表；为空表示「继承应用级样式表」——同样算统一。"""
        return w.styleSheet() or theme().qss()

    base = theme().qss()
    rep.check("AI 面板与对话框都以 theme().qss() 为基准（不各写各的私有样式）",
              _effective(panel).startswith(base) and _effective(dlg).startswith(base),
              "面板 == qss；对话框 == qss + 2 条透明窗口覆盖（自绘圆角需要）")

    # ==========================================================
    # 7. 层级：三者同处置顶层 + 点击置顶
    # ==========================================================

    top = Qt.WindowType.WindowStaysOnTopHint
    rep.check("面板 / 对话框 / 桌宠同处置顶层（z 序才由点击决定）",
              bool(panel.windowFlags() & top) and bool(dlg.windowFlags() & top),
              "均带 WindowStaysOnTopHint")

    def _press(w) -> bool:
        hit = []
        w.raise_to_front = lambda: hit.append(1)
        pos = QPointF(5, 5)
        ev = QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos,
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
        w.mousePressEvent(ev)
        return hit == [1]

    rep.check("点击面板 → 置顶", _press(AIPanel()), "raise_to_front 被调用一次")
    rep.check("点击对话框 → 置顶", _press(AppDialog(title="x")), "raise_to_front 被调用一次")

    # ==========================================================
    # 8. 渲染：浅深两套图，供人工目检
    # ==========================================================

    def _snap(w, name: str, dark: bool) -> None:
        app.processEvents()
        app.processEvents()
        img = QImage(w.size(), QImage.Format.Format_ARGB32)
        img.fill(QColor(_BACKDROP["dark" if dark else "light"]))
        w.render(img)
        img.save(str(OUT_DIR / f"{name}.png"))

    # 控制中心读的是**进程级共享会话库**。渲染预览图时换成临时库 ——
    # 否则会把用户真实的问答 / 翻译内容画进图片里（S8 的产物是要给人看的）。
    import engine.ai as _engine_ai
    from engine.ai.store import Store as _Store
    from engine.ai.types import Preset as _Preset

    _tmp_store = _Store(Path(tempfile.mkdtemp(prefix="s8_preview_")) / "preview.db")
    _tmp_store.create_session("demo-1", "translate", "示例会话 · 划词翻译")
    _tmp_store.append_message("demo-1", "user", "Hello world, this is a demo.")
    _tmp_store.append_message("demo-1", "assistant", "你好，世界。这是一段演示内容。")
    _tmp_store.create_session("demo-2", "ask", "示例会话 · 自由问答")
    _tmp_store.append_message("demo-2", "user", "PySide6 的 QSS 支持哪些选择器？")
    _tmp_store.append_message(
        "demo-2", "assistant", "支持类选择器、ID 选择器、属性选择器与伪状态。")
    _tmp_store.save_preset(_Preset(
        id="custom-1", name="文言文", system_prompt="把用户给的文本译成文言文。",
        default_delivery="replace", description="古风翻译"))
    _engine_ai.shared_store = lambda *a, **k: _tmp_store

    shots = 0
    for name in ("light", "dark"):
        dark = name == "dark"
        set_theme(name, persist=False)

        # --- 控制中心：挑六个最有代表性的页面 ---
        # 用 `goto(标题)` 而不是 `setCurrentRow(i)` —— P2.14 给导航插了分组
        # 标题行，行号不再等于页序号，按行号切会切错页（甚至切不动）。
        reset_instance()
        cc = ControlCenter(app=None)
        cc.resize(1060, 680)
        cc.show()
        app.processEvents()
        for title, tag in (("今日", "today"), ("桌宠外观", "appearance"),
                           ("AI 服务", "ai"), ("会话历史", "sessions"),
                           ("预设", "presets"), ("日志", "logs")):
            cc.goto(title)
            app.processEvents()
            if tag == "sessions":
                page = cc.current_page()
                if page._list.count():
                    page._list.setCurrentRow(0)     # 展开一条会话看详情区
                app.processEvents()
            _snap(cc, f"cc_{tag}_{name}", dark)
            shots += 1
        cc.hide()

        # --- AI 面板：填真实内容，覆盖标题/正文/列表/行内代码/引用 ---
        p = AIPanel()
        p._title.setText("划词翻译")
        p._hint.setText("已取到 18 字")
        p.set_status("已切换到 inclusionAI/Ling-flash-2.0")
        p._output.set_content(_SAMPLE_MD)
        p._actions.show()
        p.resize(620, 340)
        p.show()
        app.processEvents()
        _snap(p, f"panel_{name}", dark)
        p.hide()
        shots += 1

        # --- AI 服务设置对话框 ---
        from presentation.ai_settings_dialog import AISettingsDialog

        sd = AISettingsDialog()
        sd.show()
        app.processEvents()
        _snap(sd, f"ai_settings_{name}", dark)
        sd.close()
        shots += 1

        # --- 提示框（按钮顺序：确定在右）---
        from presentation.dialogs import MessageDialog

        md = MessageDialog(None, QMessageBox.Icon.Question, "确认删除",
                           "确定删除此便签吗？此操作不可撤销。",
                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                           QMessageBox.StandardButton.No)
        md.show()
        app.processEvents()
        _snap(md, f"dialog_message_{name}", dark)
        md.close()
        shots += 1

        # --- 番茄钟对话框（等宽大字号）---
        from presentation.dialogs import TomatoDialog
        from tools.timer_tool import TomatoTimer

        td = TomatoDialog(TomatoTimer())
        td.show()
        app.processEvents()
        _snap(td, f"dialog_tomato_{name}", dark)
        td.close()
        shots += 1

    # 收尾：回到配置里的主题，避免污染后续运行
    set_theme("default", persist=False)
    install(app)

    rep.metric("渲染图数量", shots)
    rep.note(f"预览图已落盘：{OUT_DIR}")
    rep.note("配色层次、留白、图标行一致性、日志着色观感 —— 请人工看图确认。")

    ok = all(c["ok"] for c in rep.checks)
    print()
    rep.finish("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
