# -*- coding: utf-8 -*-
"""Theme —— 全应用唯一的主题对象。

它管三件事
    1. **颜色**：持有当前 `Palette`，`color(key)` 返回 QColor。
    2. **样式表**：`qss()` 从 Palette 生成，交给 QApplication 或单个窗口。
    3. **调色板**：`qt_palette()` 生成 QPalette —— Fusion 基样式靠它给
       那些 QSS 覆盖不到的地方（原生对话框、菜单勾选、disabled 态）上色。

为什么颜色必须集中在这里
    规格要求「禁止在 QSS 中写死颜色 hex 值」。只要有一个窗口自己拼颜色，
    换主题时它就不跟着变 —— 这正是 P2.6 之前面板深色 / 对话框浅色的成因。

为什么是 QObject
    主题切换要通知所有常驻窗口。`changed` 信号让窗口自己订阅，
    而不是由切换方去逐个枚举窗口（后者必然漏掉将来新增的窗口）。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

from . import qss as _qss
from .tokens import (
    DARK,
    FONT_SIZE,
    LIGHT,
    PALETTES,
    Palette,
    mono_font_qfamilies,
    ui_font_qfamilies,
)

# ---------------------------------------------------------------- 取值

THEME_DEFAULT = "default"
THEME_LIGHT = "light"
THEME_DARK = "dark"

_VALID = (THEME_DEFAULT, THEME_LIGHT, THEME_DARK)

#: 配置键（写在一处，避免字符串散落）
CONFIG_KEY = "appearance.theme"

#: "default" 落到哪一套。参考 Win11 原生应用默认浅色。
_DEFAULT_RESOLVES_TO = THEME_LIGHT

#: 旧 token 名 → 新 token 名。
#: 历史代码（giwifi 插件、早期对话框）用的是 glass_widgets 的键名，
#: 保留映射就不必为了改名去改第三方插件。
_LEGACY_ALIASES = {
    "primary": "accent",
    "primary_hover": "accent_pressed",
    "surface_hover": "hover",
    "input_border": "border",
    "text_sec": "text_secondary",
    "text_ter": "text_disabled",
    "track_off": "border",
    "focus_ring": "accent",
}


def normalize_theme(name) -> str:
    """把任意输入规整成合法主题名；非法值一律落到 default。

    配置文件是用户可手改的，这里必须容错 —— 一个错别字不该让整个 UI 崩掉。
    """
    if name is None:
        return THEME_DEFAULT
    text = str(name).strip().lower()
    return text if text in _VALID else THEME_DEFAULT


def resolve_theme(name) -> str:
    """把 default 解析成实际使用的 "light" / "dark"。"""
    resolved = normalize_theme(name)
    return _DEFAULT_RESOLVES_TO if resolved == THEME_DEFAULT else resolved


def is_dark(name) -> bool:
    return resolve_theme(name) == THEME_DARK


# ---------------------------------------------------------------- 字体

def make_font(size: float = FONT_SIZE,
              weight: QFont.Weight = QFont.Weight.Normal,
              mono: bool = False) -> QFont:
    """构造字体。**一律用 pt**，跟随系统 DPI 缩放（禁止写死 px）。"""
    f = QFont()
    f.setFamilies(mono_font_qfamilies() if mono else ui_font_qfamilies())
    f.setPointSizeF(float(size))
    f.setWeight(weight)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


def has_family(name: str) -> bool:
    """系统里有没有这个字体（用于挑等宽字体）。"""
    try:
        return name in QFontDatabase.families()
    except Exception:  # noqa: BLE001 —— 无 GUI 环境下直接放弃探测
        return False


# ---------------------------------------------------------------- Theme

class Theme(QObject):
    """当前主题（进程内单例，原地可变）。"""

    changed = Signal()

    def __init__(self, name: str = THEME_DEFAULT):
        super().__init__()
        #: 写回配置时用的原始值（default / light / dark），
        #: 与 `name`（已解析成 light / dark）刻意分开 —— 用户选的是
        #: "default"，配置里就该存 "default"，而不是被解析后的结果覆盖。
        self._config_value = normalize_theme(name)
        self._name = resolve_theme(name)
        self._palette = PALETTES[self._name]
        self._qss_cache: str | None = None
        self._font = make_font(FONT_SIZE)
        self._font_bold = make_font(FONT_SIZE, QFont.Weight.DemiBold)
        self._font_title = make_font(FONT_SIZE + 3, QFont.Weight.DemiBold)
        self._font_mono = make_font(FONT_SIZE, mono=True)
        self._font_mono_bold = make_font(FONT_SIZE, QFont.Weight.DemiBold, mono=True)

    # ----- 数据 -----

    @property
    def palette(self) -> Palette:
        return self._palette

    @property
    def name(self) -> str:
        """实际生效的 "light" / "dark"。"""
        return self._name

    @property
    def dark(self) -> bool:
        return self._palette.dark

    @property
    def config_value(self) -> str:
        """写回配置时用的值（default / light / dark）。"""
        return self._config_value

    # ----- 字体 -----

    @property
    def font(self) -> QFont:
        return self._font

    @property
    def font_bold(self) -> QFont:
        return self._font_bold

    @property
    def font_title(self) -> QFont:
        return self._font_title

    @property
    def font_mono(self) -> QFont:
        return self._font_mono

    @property
    def font_mono_bold(self) -> QFont:
        return self._font_mono_bold

    # ----- 颜色 -----

    def color(self, key: str) -> QColor:
        """取颜色。支持新 token 名与旧 `glass_widgets` 别名。"""
        data = self._palette.as_dict()
        if key not in data:
            key = _LEGACY_ALIASES.get(key, key)
        raw = data.get(key)
        if raw is None:
            # 不静默返回黑色 —— 那会让「打错 token 名」变成难查的视觉 bug
            raise KeyError(f"未知颜色 token: {key!r}")
        c = QColor(raw)
        if not c.isValid():          # rgba(...) 字符串
            c = _parse_rgba(raw)
        return c

    def has(self, key: str) -> bool:
        data = self._palette.as_dict()
        return key in data or key in _LEGACY_ALIASES

    def rgba(self, key: str, alpha: float) -> str:
        """把某个 token 的颜色以指定透明度输出成 QSS 的 rgba()。"""
        c = self.color(key)
        return f"rgba({c.red()}, {c.green()}, {c.blue()}, {round(alpha * 255)})"

    # ----- 样式 -----

    def qss(self) -> str:
        """全应用样式表（带缓存，换主题时失效）。"""
        if self._qss_cache is None:
            self._qss_cache = _qss.build_qss(self)
        return self._qss_cache

    def qt_palette(self) -> QPalette:
        return _qss.build_qt_palette(self)

    # ----- 切换 -----

    def set_name(self, name: str) -> bool:
        """切到另一套配色；返回是否**真的**发生了变化。"""
        resolved = resolve_theme(name)
        self._config_value = normalize_theme(name)
        if resolved == self._name:
            return False
        self._name = resolved
        self._palette = PALETTES[resolved]
        self._qss_cache = None
        self.changed.emit()
        return True


def _parse_rgba(text: str) -> QColor:
    """解析 `rgba(r, g, b, a)`（a 为 0~255）。"""
    try:
        inner = text[text.index("(") + 1: text.rindex(")")]
        parts = [int(p.strip()) for p in inner.split(",")]
        return QColor(*parts[:4])
    except Exception:  # noqa: BLE001
        return QColor("#FF00FF")     # 显眼的洋红：一眼看出 token 写错了


# ---------------------------------------------------------------- 单例

_theme: Theme | None = None
#: 已生效的主题名（**权威值**，由 set_theme 维护）。
#: 为什么不每次读配置：`set_theme(persist=False)`（测试 / 临时预览）时配置没变，
#: 若去读配置就会与内存里实际生效的主题脱节。
_name: str | None = None


def theme() -> Theme:
    """当前主题（进程内单例，原地可变）。"""
    global _theme
    if _theme is None:
        _theme = Theme(_current_name())
    return _theme


def theme_name() -> str:
    """当前生效的配置值（default / light / dark）。"""
    return _current_name()


def set_theme(name: str, persist: bool = True) -> Theme:
    """切换应用主题：写配置 + 原地更新单例 + 重新应用到 QApplication。

    Args:
        name: 主题名（非法值会被规整成 default）
        persist: 是否写回配置文件。测试里传 False，避免污染用户配置。

    Returns:
        更新后的 Theme（与 `theme()` 是同一对象）
    """
    global _name

    resolved = normalize_theme(name)
    t = theme()
    changed = t.set_name(resolved)
    _name = resolved

    if persist:
        # 延迟导入：config_manager 属于数据层，放模块顶层会让
        # 纯 UI 测试也被迫加载配置系统。
        from data.config_manager import config_manager

        config_manager.set(CONFIG_KEY, resolved)
        config_manager.save()

    if changed:
        _reapply(t)
    return t


def install(app) -> Theme:
    """把当前主题装到 QApplication 上（Fusion + QPalette + QSS + 字体）。

    在 `UIManager.initialize()` 里调用一次。之后 `set_theme()` 会自动重装。
    """
    t = theme()
    _apply_to(app, t)
    _installed_apps.append(app)
    return t


_installed_apps: list = []


def _reapply(t: Theme) -> None:
    """主题变化后重新装到所有已注册的 QApplication。"""
    for app in list(_installed_apps):
        try:
            _apply_to(app, t)
        except RuntimeError:      # 底层 C++ 对象已销毁
            _installed_apps.remove(app)


def _apply_to(app, t: Theme) -> None:
    # Fusion：唯一一个在所有平台都吃 QSS 的基样式。用系统原生样式时
    # Windows 的 UxTheme 会忽略大量 QSS 属性（圆角、hover 等直接失效）。
    app.setStyle("Fusion")
    app.setPalette(t.qt_palette())
    app.setFont(t.font)
    app.setStyleSheet(t.qss())


# ---------------------------------------------------------------- 内部

def _current_name() -> str:
    """当前生效的配置值（首次访问从配置读，之后由 set_theme 维护）。"""
    global _name
    if _name is None:
        _name = normalize_theme(_read_config_name())
    return _name


def _read_config_name() -> str:
    """读配置里的主题名。任何异常都退回 default（UI 不该因配置崩）。"""
    try:
        from data.config_manager import config_manager

        return config_manager.get(CONFIG_KEY, THEME_DEFAULT)
    except Exception:  # noqa: BLE001
        return THEME_DEFAULT


def reset_for_tests() -> None:
    """清掉进程级缓存（测试专用）。"""
    global _theme, _name
    _theme = None
    _name = None
    _installed_apps.clear()
