# -*- coding: utf-8 -*-
"""应用级主题源 —— 对 `presentation.design` 的稳定门面。

为什么还要这一层
    `presentation.design` 是新的设计系统（tokens / theme / qss / icons / widgets）。
    但项目里已经有一批代码按老名字引用主题：`app_theme()`、`set_theme()`、
    `theme_name()`、`THEME_DARK` …，第三方插件（giwifi）也在用。
    这一层把老 API 映射到新实现，于是迁移可以逐个窗口进行，
    而不是一次性改到所有文件 —— 那种改法必然漏。

**新代码请直接 `from presentation.design import theme`。**
本模块只为兼容而存在。

关于「同一个实例」
    `app_theme()` 返回的是 `design.theme()` 那个**缓存单例**，
    `set_theme()` 在它上面原地改。于是所有订阅了 `changed` 信号的控件
    会一起换肤，不需要重建控件树。
"""
from __future__ import annotations

# 直接导入函数，而不是 `import presentation.design.theme as m` ——
# 包 `__init__` 把子模块名 `theme` 重绑定成了同名函数，
# 走属性访问会拿到函数而非模块，容易看错。
from presentation.design import set_theme as _set_theme
from presentation.design import theme as _theme
from presentation.design import theme_name as _theme_name
from presentation.design.theme import (  # noqa: F401
    CONFIG_KEY,
    THEME_DARK,
    THEME_DEFAULT,
    THEME_LIGHT,
    Theme,
    is_dark,
    normalize_theme,
    resolve_theme,
)

__all__ = [
    "app_theme", "set_theme", "theme_name", "normalize_theme", "resolve_theme",
    "is_dark", "Theme", "THEME_DEFAULT", "THEME_LIGHT", "THEME_DARK",
    "CONFIG_KEY", "reset_cache",
]


def app_theme() -> Theme:
    """当前应用主题（进程内单例，原地可变）。"""
    return _theme()


def theme_name() -> str:
    """当前生效的配置值（default / light / dark）。"""
    return _theme_name()


def set_theme(name: str, persist: bool = True) -> Theme:
    """切换应用主题：写配置 + 原地更新单例 + 重新应用到 QApplication。"""
    return _set_theme(name, persist=persist)


def reset_cache() -> None:
    """清掉进程级缓存（测试专用）。

    保留这个名字是为了让老测试的 `_reset_theme_state()` 能平滑迁移 ——
    新代码请用 `presentation.design.reset_for_tests()`。
    """
    from presentation.design import reset_for_tests

    reset_for_tests()
