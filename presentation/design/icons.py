# -*- coding: utf-8 -*-
"""图标 —— 统一来源的内联 SVG（Lucide 风格），按主题色现场着色。

为什么不用 PNG / 不写死颜色
    · PNG 在 HiDPI 下糊；SVG 由 Qt 的 SVG 图标引擎按需光栅化，永远清晰。
    · 「深浅色各一套」不是两份文件，而是**同一份路径数据 + 不同描边色**：
      描边色从 `Theme` 取，于是换主题时图标自动跟着变，不可能漏。

两种用法
    `icon("gear")`        → QIcon，给按钮 / 菜单 / 工具栏用
    `qss_urls(theme)`     → 写盘后的 file:// 路径，给 QSS 的 `image: url(...)`
                            （勾选标记、下拉箭头这类 QSS 画不出来的图形）

写盘位置
    `~/.pet_demo/cache/icons/<主题>/<名>-<色>-<尺寸>.svg`
    每次进程内只写一次；文件内容随主题变化，所以深浅两套并存、互不覆盖。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from .tokens import ICON_SIZE

# ================================================================
# 路径数据（24×24 网格，描边式，stroke-linecap/linejoin 圆角）
# 取自 Lucide（ISC 许可）的几何形状，必要时按本项目网格微调。
# ================================================================

ICONS: dict[str, str] = {
    # --- 主题 / 外观 ---
    "sun": '<circle cx="12" cy="12" r="4.2"/>'
           '<path d="M12 1.8v2.4M12 19.8v2.4M4.2 4.2l1.7 1.7M18.1 18.1l1.7 1.7'
           'M1.8 12h2.4M19.8 12h2.4M4.2 19.8l1.7-1.7M18.1 5.9l1.7-1.7"/>',
    "moon": '<path d="M20.5 14.5A8.5 8.5 0 1 1 9.5 3.5a7 7 0 0 0 11 11Z"/>',
    "palette": '<path d="M12 3.5a8.5 8.5 0 0 0 0 17c1.4 0 2-.9 2-1.8 0-.9-.6-1.5-.6-2.2'
               '0-.8.7-1.5 1.6-1.5h1.3a3.7 3.7 0 0 0 3.7-3.7C20 6.9 16.4 3.5 12 3.5Z"/>'
               '<circle cx="8" cy="10" r="1.1"/><circle cx="12" cy="7.8" r="1.1"/>'
               '<circle cx="16" cy="10" r="1.1"/>',
    "paw": '<ellipse cx="7" cy="9" rx="1.9" ry="2.4"/><ellipse cx="12" cy="7" rx="1.9" ry="2.4"/>'
           '<ellipse cx="17" cy="9" rx="1.9" ry="2.4"/>'
           '<path d="M12 11.5c3 0 5 2 5 4.2 0 1.9-1.6 3-3.4 3-.7 0-1.1-.3-1.6-.3'
           's-.9.3-1.6.3c-1.8 0-3.4-1.1-3.4-3 0-2.2 2-4.2 5-4.2Z"/>',
    "image": '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/>'
             '<circle cx="9" cy="10" r="1.6"/>'
             '<path d="M4.5 17.5 9.8 12.5l3.4 3.2 3-2.6 3.8 3.4"/>',

    # --- 行为 / 工具 ---
    "sliders": '<path d="M4 7.5h9M17 7.5h3M4 16.5h3M11 16.5h9"/>'
               '<circle cx="15" cy="7.5" r="2.2"/><circle cx="9" cy="16.5" r="2.2"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.2l3.2 2"/>',
    "note": '<path d="M15.5 3.5H6.5A1.5 1.5 0 0 0 5 5v14a1.5 1.5 0 0 0 1.5 1.5h8L19 16V5'
            'a1.5 1.5 0 0 0-1.5-1.5Z"/><path d="M14.5 20.5v-4.5H19"/>',
    "rocket": '<path d="M13.5 4.5c3.5-1.5 6-1 6-1s.5 2.5-1 6c-1.2 2.8-3.7 5.3-6 6.5L9 12.5'
              'C10.2 10.2 12.7 5.7 13.5 4.5Z"/><path d="M9 12.5 5.5 12l1.8-3.2 3.4-.6"/>'
              '<path d="M12.5 16l-.5 3.5-3.2-1.8-.6-3.4"/><path d="M6.5 17.5 4 20"/>',
    "keyboard": '<rect x="2.5" y="6.5" width="19" height="11" rx="2"/>'
                '<path d="M6 10h.01M9.5 10h.01M13 10h.01M16.5 10h.01M6.5 13.5h11"/>',

    # --- AI ---
    "sparkles": '<path d="M11 3.5l1.9 4.6 4.6 1.9-4.6 1.9L11 16.5 9.1 11.9 4.5 10l4.6-1.9Z"/>'
                '<path d="M18 15l.9 2.1L21 18l-2.1.9L18 21l-.9-2.1L15 18l2.1-.9Z"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="1.6"/>'
           '<rect x="9.5" y="9.5" width="5" height="5" rx="1"/>'
           '<path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>',
    "terminal": '<rect x="2.8" y="4.2" width="18.4" height="15.6" rx="2"/>'
                '<path d="M7 9.5l3 2.5-3 2.5"/><path d="M12.5 15h4.5"/>',

    # --- 插件 / 系统 ---
    "puzzle": '<path d="M10 3.5a2 2 0 0 1 4 0V5h3.5a1 1 0 0 1 1 1v3.5h1.5a2 2 0 0 1 0 4H18.5V17'
              'a1 1 0 0 1-1 1H14v1.5a2 2 0 0 1-4 0V18H6.5a1 1 0 0 1-1-1v-3.5H4a2 2 0 0 1 0-4h1.5'
              'V6a1 1 0 0 1 1-1H10Z"/>',
    # 「隐私与数据」页用（v1.7.0）：盾 + 对勾
    "shield": '<path d="M12 3 20 6v5.5c0 4.6-3.2 8.2-8 9.5-4.8-1.3-8-4.9-8-9.5V6Z"/>'
              '<path d="M8.6 12.2l2.5 2.5 4.5-4.7"/>',
    "wrench": '<path d="M14.5 6.5a4.5 4.5 0 0 0 5.9 5.9l-8.2 8.2a2.5 2.5 0 0 1-3.5-3.5Z"/>',
    "power": '<path d="M12 3.5v8"/><path d="M6.8 6.8a7.5 7.5 0 1 0 10.4 0"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><path d="M12 7.6h.01"/>',
    "monitor": '<rect x="2.8" y="4" width="18.4" height="12.5" rx="1.6"/>'
               '<path d="M8.5 20.5h7M12 16.5v4"/>',

    # --- 日志 / 数据 ---
    "scroll": '<path d="M6 3.5h11A1.5 1.5 0 0 1 18.5 5v13a2.5 2.5 0 0 0 2.5 2.5H8'
              'a2.5 2.5 0 0 1-2.5-2.5V5A1.5 1.5 0 0 1 6 3.5Z"/>'
              '<path d="M9 8.5h6M9 12h6M9 15.5h4"/>',
    "list": '<path d="M8 6.5h12M8 12h12M8 17.5h12"/><path d="M4 6.5h.01M4 12h.01M4 17.5h.01"/>',
    # 「趋势」页用：折线向上 + 轴线（P2.14）
    "trend": '<path d="M3.5 20.5h17"/><path d="M3.5 20.5V3.8"/>'
             '<path d="M6.8 15.8 11 11.4l3.2 3.2 6-6.4"/>'
             '<path d="M16.4 8.2h3.8v3.8"/>',
    # 「协同记录」页用：带对勾的文档 = 被核对过、签过字的记录（v1.8.0）。
    # 为什么不用 check-circle：那是「操作成功」的通用语义，而这一页
    # 表达的是「留档、可审计」——文档比圆形更贴近「凭据」。
    "file-check": '<path d="M14 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10'
                  'a1.5 1.5 0 0 0 1.5-1.5V8.5Z"/>'
                  '<path d="M14 3.5V8.5h4.5"/><path d="M9.2 14.8l2 2 3.6-4"/>',

    # --- 动作 ---
    "refresh": '<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1"/><path d="M20.5 3.5v5h-5"/>',
    "folder": '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4l2 2.5h9A1.5 1.5 0 0 1 21 9v9'
              'a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18Z"/>',
    "save": '<path d="M19.5 20.5h-15a1 1 0 0 1-1-1v-15a1 1 0 0 1 1-1h11l5 5v11a1 1 0 0 1-1 1Z"/>'
            '<path d="M7 3.5v6h8v-6"/><path d="M7 20.5v-6h10v6"/>',
    "play": '<path d="M7.5 4.8 19 12 7.5 19.2Z"/>',
    "pause": '<rect x="7" y="5" width="3.6" height="14" rx="1.4"/>'
             '<rect x="13.4" y="5" width="3.6" height="14" rx="1.4"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.2"/>',
    "trash": '<path d="M4 6.5h16"/><path d="M9.5 6.5V4.8A1.3 1.3 0 0 1 10.8 3.5h2.4'
             'a1.3 1.3 0 0 1 1.3 1.3v1.7"/>'
             '<path d="M6.5 6.5 7.4 19a1.5 1.5 0 0 0 1.5 1.4h6.2a1.5 1.5 0 0 0 1.5-1.4'
             'l.9-12.5"/>',
    "eraser": '<path d="M7.5 20.5h13"/><path d="M17.8 12.7 11 19.5H6.6L4.4 17.3a1.5 1.5 0 0 1 0-2.1'
              'l9.6-9.6a1.5 1.5 0 0 1 2.1 0l3.8 3.8a1.5 1.5 0 0 1 0 2.1Z"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.4 15.4 21 21"/>',
    "gear": '<circle cx="12" cy="12" r="3.2"/>'
            '<path d="M12 2.5v2.6M12 18.9v2.6M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8'
            'M2.5 12h2.6M18.9 12h2.6M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"/>',
    "external": '<path d="M14 4.5h5.5V10"/><path d="M19.5 4.5 11 13"/>'
                '<path d="M18 14v4.5A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 18.5v-11'
                'A1.5 1.5 0 0 1 5.5 6H10"/>',
    "copy": '<rect x="8.5" y="8.5" width="12" height="12" rx="1.8"/>'
            '<path d="M5.5 15.5h-1A1.5 1.5 0 0 1 3 14V4.5A1.5 1.5 0 0 1 4.5 3H14'
            'a1.5 1.5 0 0 1 1.5 1.5v1"/>',
    "close": '<path d="M5.5 5.5 18.5 18.5M18.5 5.5 5.5 18.5"/>',
    "minus": '<path d="M5 12h14"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "check": '<path d="M4.8 12.6 9.6 17.4 19.2 6.9"/>',
    "dot": '<circle cx="12" cy="12" r="4.6" fill="currentColor" stroke="none"/>',
    "chevron-right": '<path d="M9.5 5.5 16 12l-6.5 6.5"/>',
    "chevron-down": '<path d="M5.5 9.5 12 16l6.5-6.5"/>',
    "chevron-up": '<path d="M5.5 14.5 12 8l6.5 6.5"/>',
    "alert": '<path d="M12 3.6 21.5 20H2.5Z"/><path d="M12 9.5v4.5"/><path d="M12 17.2h.01"/>',
    "ok-circle": '<circle cx="12" cy="12" r="9"/><path d="M8 12.3l2.7 2.7L16 9.6"/>',
    "x-circle": '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/>'
           '<circle cx="12" cy="12" r="3"/>',
    "pin": ('<path d="M12 17.2V21"/>'
            '<path d="M8.6 10.8A2 2 0 0 1 7.5 12.6l-1.6.8A2 2 0 0 0 4.8 15.2V16a1 1 0 0 0 1 1'
            'h12.4a1 1 0 0 0 1-1v-.8a2 2 0 0 0-1.1-1.8l-1.6-.8a2 2 0 0 1-1.1-1.8V7.2'
            'a1 1 0 0 1 1-1 2 2 0 0 0 0-4H7.6a2 2 0 0 0 0 4 1 1 0 0 1 1 1Z"/>'),
    "send": '<path d="M20.5 3.5 3.5 10.5l6.4 2.6 2.6 6.4Z"/><path d="M20.5 3.5 9.9 13.1"/>',
    "history": '<path d="M3.2 12a8.8 8.8 0 1 0 2.6-6.2L3.2 8.4"/>'
               '<path d="M3.2 3.6v4.8h4.8"/>'
               '<path d="M12 7.6V12l3.4 2"/>',
    "pencil": '<path d="M17 3.2a2.8 2.8 0 0 1 4 4L7.6 20.6 2.4 21.8l1.2-5.2Z"/>'
              '<path d="M14.6 5.6 18.4 9.4"/>',
    "eye-off": '<path d="M4 4l16 16"/>'
               '<path d="M9.9 5.9A9.6 9.6 0 0 1 12 5.7c6 0 9.5 6.3 9.5 6.3'
               'a17 17 0 0 1-3.6 4.2"/>'
               '<path d="M6.3 8A17 17 0 0 0 2.5 12S6 18.3 12 18.3c1.2 0 2.3-.2 3.3-.6"/>'
               '<path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
}

#: 这些图标是「实心」的（描边会让小尺寸下糊成一团）
FILLED = {"dot", "play", "stop", "pause"}

#: 描边宽度（相对 24×24 网格）
STROKE_WIDTH = 1.9


# ================================================================
# SVG 生成
# ================================================================

def svg_markup(name: str, color: str, size: int = ICON_SIZE,
               stroke_width: float = STROKE_WIDTH) -> str:
    """生成一份完整的 SVG 文本。

    显式写 `width`/`height`：QSS 的 `image: url(...)` 不做缩放，
    图片按自身尺寸绘制 —— 不带尺寸的 SVG 在不同平台表现不一致。

    未知图标名返回**空 SVG** 而不是抛异常：图标名是字符串字面量，
    拼错一次就让整个窗口构造失败，代价太大。空图标在界面上就是一块
    空白，肉眼能发现，但不会把程序带崩。见 `icon()` 的 null 约定。
    """
    body = ICONS.get(name, "")
    if name in FILLED:
        stroke, fill = "none", color
    else:
        stroke, fill = color, "none"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="{fill}" stroke="{stroke}" '
        f'stroke-width="{stroke_width}" stroke-linecap="round" stroke-linejoin="round">'
        f'{body}</svg>'
    )


def has(name: str) -> bool:
    return name in ICONS


# ================================================================
# 缓存与落盘
# ================================================================

_cache_root: Path | None = None
_written: set = set()
_icon_cache: dict = {}


def cache_root() -> Path:
    global _cache_root
    if _cache_root is None:
        from data.paths import pet_path

        _cache_root = pet_path("cache", "icons")
    return _cache_root


def svg_file(name: str, color: str, size: int = ICON_SIZE) -> Path:
    """把 SVG 写到磁盘并返回路径（进程内同参数只写一次）。"""
    safe = color.lstrip("#").replace("#", "")
    key = f"{name}-{safe}-{size}"
    path = cache_root() / f"{key}.svg"
    if key not in _written:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(svg_markup(name, color, size), encoding="utf-8")
        except OSError:
            # 写不进去（只读目录 / 权限）时退回临时目录 —— 图标不该让 UI 崩
            import tempfile

            path = Path(tempfile.gettempdir()) / f"petdemo-{key}.svg"
            path.write_text(svg_markup(name, color, size), encoding="utf-8")
        _written.add(key)
    return path


def _qss_url(path: Path) -> str:
    return str(path).replace("\\", "/")


def _theme_color_hex(t, role: str) -> str:
    return t.color(role).name()


def qss_urls(t) -> dict:
    """QSS 内嵌图形所需的 file:// 路径（按当前主题着色）。"""
    text = _theme_color_hex(t, "text_secondary")
    accent_text = _theme_color_hex(t, "accent_text")
    disabled = t.color("text_disabled")
    disabled_hex = disabled.name()

    return {
        # 勾选标记：画在强调色底上，所以用 accent_text（白/深）
        "check": _qss_url(svg_file("check", accent_text, 12)),
        "dot": _qss_url(svg_file("dot", accent_text, 10)),
        # 箭头用次要文字色，深色主题下才不会糊在底色里
        "chevron-down": _qss_url(svg_file("chevron-down", text, 12)),
        "chevron-up": _qss_url(svg_file("chevron-up", text, 10)),
        "chevron-right": _qss_url(svg_file("chevron-right", text, 12)),
        "chevron-down-disabled": _qss_url(svg_file("chevron-down", disabled_hex, 12)),
    }


# ================================================================
# QIcon 工厂
# ================================================================

def icon(name: str, color: str | None = None, size: int = ICON_SIZE) -> QIcon:
    """按名取图标。`color` 省略时用当前主题的主文字色。

    缓存键含颜色与尺寸，所以主题切换后取到的是新图标，无需手动失效。

    未知名字返回**空 QIcon**（`isNull()` 为真）而不是抛异常 ——
    图标名是手写的字符串字面量，拼错不该让整个窗口构造失败。
    空图标在界面上表现为「按钮没图案」，肉眼能发现但不会崩。
    """
    if name not in ICONS:
        return QIcon()
    if color is None:
        from .theme import theme

        color = theme().color("text").name()
    key = (name, color, size)
    cached = _icon_cache.get(key)
    if cached is not None:
        return cached
    ic = QIcon(_qss_url(svg_file(name, color, size)))
    _icon_cache[key] = ic
    return ic


def themed(name: str, role: str = "text", size: int = ICON_SIZE) -> QIcon:
    """按语义角色取图标（text / text_secondary / accent / error …）。"""
    from .theme import theme

    return icon(name, theme().color(role).name(), size)


def pixmap(name: str, color: str, size: int = ICON_SIZE,
           dpr: float = 1.0) -> QPixmap:
    """直接光栅化成 QPixmap（少见的自绘场景用）。"""
    px = QPixmap(QSize(int(size * dpr), int(size * dpr)))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _render_svg(name, color, size, p)
    p.end()
    return px


def _render_svg(name: str, color: str, size: int, painter: QPainter) -> None:
    """用 QtSvg 把内联 SVG 画到 painter 上（不落盘）。"""
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(svg_markup(name, color, size).encode("utf-8"))
    renderer.render(painter)


def clear_cache() -> None:
    """清掉进程内缓存（测试专用）。"""
    _icon_cache.clear()
    _written.clear()
