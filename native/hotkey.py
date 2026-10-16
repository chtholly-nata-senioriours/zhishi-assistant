# -*- coding: utf-8 -*-
"""全局热键服务。

主后端：Win32 `RegisterHotKey` + Qt `QAbstractNativeEventFilter`。
    选它而不是键盘钩子的原因：
      - 由系统投递 WM_HOTKEY，不与 `sensor/input_monitor.py` 的 pynput 低级钩子抢事件；
      - 在独占全屏、提权窗口等场景下比钩子更可靠（S1 spike 已实测共存）。
    代价：组合键被系统独占，前台程序收不到该按键（这正是我们想要的）。

回退后端：`pynput.keyboard.GlobalHotKeys`（非 Windows 平台）。

S1 spike 实测结论
    Alt+Q / Alt+T / Alt+S 均可注册；重复注册返回 1409
    （ERROR_HOTKEY_ALREADY_REGISTERED），已映射为「注册失败」。
"""
from __future__ import annotations

import sys
from typing import Callable, Dict, Optional, Tuple

from PySide6.QtCore import QAbstractNativeEventFilter

# ---- Win32 常量 ----
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

_MODS = {
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
}

_NAMED_VK = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "tab": 0x09, "backspace": 0x08, "delete": 0x2E, "insert": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD,
    "\\": 0xDC, ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF,
}


def parse_combo(combo: str) -> Tuple[int, int]:
    """把 "ctrl+alt+f9" 解析为 (modifiers, virtual_key)。

    Raises:
        ValueError: 组合键格式非法。
    """
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"空的组合键: {combo!r}")

    mods = 0
    key = None
    for p in parts:
        if p in _MODS:
            mods |= _MODS[p]
        elif key is None:
            key = p
        else:
            raise ValueError(f"组合键含多个主键: {combo!r}")

    if key is None or mods == 0:
        raise ValueError(f"组合键必须包含至少一个修饰键和一个主键: {combo!r}")

    return mods, _vk(key)


def _vk(key: str) -> int:
    if key in _NAMED_VK:
        return _NAMED_VK[key]
    if len(key) == 1 and key.isalpha():
        return ord(key.upper())
    if len(key) == 1 and key.isdigit():
        return ord(key)
    if len(key) >= 2 and key[0] == "f" and key[1:].isdigit():
        n = int(key[1:])
        if 1 <= n <= 24:
            return 0x70 + (n - 1)
    raise ValueError(f"无法识别的按键: {key!r}")


class _WinHotkeyFilter(QAbstractNativeEventFilter):
    """从 Qt 消息循环里捞出 WM_HOTKEY。"""

    def __init__(self, dispatch: Callable[[int], None]):
        super().__init__()
        self._dispatch = dispatch

    def nativeEventFilter(self, eventType, message):  # noqa: N802
        try:
            import ctypes
            from ctypes import wintypes

            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self._dispatch(int(msg.wParam))
        except Exception:
            pass
        return False, 0


class HotkeyService:
    """全局热键服务（单实例，由宿主创建并通过 app.hotkeys 暴露给插件）。"""

    def __init__(self):
        self.backend = "win32" if sys.platform == "win32" else "pynput"
        self._next_id = 1
        self._by_id: Dict[int, Tuple[str, Callable[[], None]]] = {}
        self._by_combo: Dict[str, int] = {}
        self._filter = None
        self._user32 = None
        self._pynput_listener = None

        if self.backend == "win32":
            import ctypes

            self._user32 = ctypes.WinDLL("user32", use_last_error=True)

    # ----- 生命周期 -----

    def install(self, app) -> None:
        """接入 Qt 消息循环。必须在 QApplication 创建后调用。"""
        if self.backend == "win32" and self._filter is None:
            self._filter = _WinHotkeyFilter(self._dispatch)
            app.installNativeEventFilter(self._filter)

    # ----- 注册 -----

    def register(self, combo: str, callback: Callable[[], None]) -> bool:
        """注册全局热键。被占用时返回 False（不抛异常）。"""
        try:
            mods, vk = parse_combo(combo)
        except ValueError:
            return False

        if combo in self._by_combo:
            return True  # 已注册同一组合键

        if self.backend == "win32":
            import ctypes
            from ctypes import wintypes

            hid = self._next_id
            self._next_id += 1
            self._user32.RegisterHotKey.restype = wintypes.BOOL
            ok = bool(
                self._user32.RegisterHotKey(
                    None, hid, mods | MOD_NOREPEAT, vk
                )
            )
            if not ok:
                return False
            self._by_id[hid] = (combo, callback)
            self._by_combo[combo] = hid
            return True

        return self._register_pynput(combo, callback)

    def unregister(self, combo: str) -> bool:
        hid = self._by_combo.pop(combo, None)
        if hid is None:
            return False
        if self.backend == "win32":
            self._user32.UnregisterHotKey(None, hid)
            self._by_id.pop(hid, None)
        else:
            self._restart_pynput()
        return True

    def unregister_all(self) -> None:
        for combo in list(self._by_combo.keys()):
            self.unregister(combo)
        self._by_id.clear()
        self._by_combo.clear()
        if self._pynput_listener is not None:
            try:
                self._pynput_listener.stop()
            except Exception:
                pass
            self._pynput_listener = None

    def registered(self) -> Dict[str, Callable[[], None]]:
        return {combo: cb for _, (combo, cb) in self._by_id.items()}

    # ----- 内部 -----

    def _dispatch(self, hid: int) -> None:
        entry = self._by_id.get(hid)
        if not entry:
            return
        _, callback = entry
        try:
            callback()
        except Exception as e:  # noqa: BLE001
            from data.log_manager import log_manager

            log_manager.error(f"热键回调异常 [{entry[0]}]: {e}")

    # --- pynput 回退后端（非 Windows）---

    def _register_pynput(self, combo: str, callback: Callable[[], None]) -> bool:
        self._by_combo[combo] = -1
        self._by_id[-len(self._by_combo)] = (combo, callback)
        self._restart_pynput()
        return True

    def _restart_pynput(self) -> None:
        try:
            from pynput import keyboard as pk

            if self._pynput_listener is not None:
                self._pynput_listener.stop()
            mapping = {}
            for _, (combo, cb) in self._by_id.items():
                mapping[_pynput_combo(combo, pk)] = cb
            self._pynput_listener = pk.GlobalHotKeys(mapping)
            self._pynput_listener.daemon = True
            self._pynput_listener.start()
        except Exception:
            pass


def _pynput_combo(combo: str, pk) -> str:
    """把 "alt+q" 转成 pynput 的 "<alt>+q" 形式。"""
    out = []
    for p in combo.split("+"):
        p = p.strip().lower()
        if p in ("alt", "ctrl", "shift", "cmd", "win"):
            out.append(f"<{p if p != 'win' else 'cmd'}>")
        else:
            out.append(p)
    return "+".join(out)
