# -*- coding: utf-8 -*-
"""系统代理层（L1）—— 代用户触达其他程序、采集屏幕与剪贴板。

设计约束：
  - **不得 import `presentation` 或 `extensions`**（依赖单向向上）。
  - **不得创建 QWidget**。本层只做系统能力，不做界面。
  - 允许使用 Qt 的**非界面**能力（QClipboard / QScreen / 事件过滤器），
    因为这些是 Qt 提供的跨平台系统抽象，比裸 Win32 API 更可靠且保真度更高。
    这是对执行框架 §4.3 的一处务实放宽，已在文档中注明。

模块：
    hotkey.py     全局热键（Win32 RegisterHotKey + Qt 消息循环）
    selection.py  选中文本 / 剪贴板（含全格式备份还原）
    capture.py    屏幕截图 / 区域选择
    injector.py   文本注入（粘贴到前台 / 逐字键入）
    foreground.py 前台窗口记录与还原

注意：本包**不能**命名为 `platform` —— 会遮蔽 Python 标准库同名模块。
"""
