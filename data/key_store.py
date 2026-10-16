# -*- coding: utf-8 -*-
"""系统密钥库 —— API Key 这类机密的统一存取口（纯 Python，零 Qt）。

为什么不让密钥留在 `user_config.json`
    配置文件是**明文 JSON**：会进备份、进同步盘、进「导出全部数据」的 zip。
    密钥写在那里，等于每一次备份都多一个泄露面。系统密钥库（Windows 凭据管理器 /
    macOS 钥匙串 / Linux Secret Service）由操作系统保管、按**当前用户**隔离，
    别的用户、别的进程都读不到 —— 这就是「权限隔离」，不靠代码自觉。

两层后端（按可用性择一，接口完全相同）
    ① 系统密钥库 `keyring`（可选依赖）：装了就用它，真正的「系统统一密钥管理」。
    ② DPAPI 加密文件（Windows 内置，零依赖）：`CryptProtectData` 按当前用户
       加密后写到 `<数据根>/secure_keys.bin`。没装 keyring 的机器也**不落地明文**。

配置里只存**引用**
    `ai.api_key_ref = "keyring:api.deepseek.com"` —— 一个名字，不是密钥本身。
    取密钥一律走 `load_key()`；直接读 `ai.api_key` 只允许作为**明文回退**
    （老用户的旧配置），且只有 `engine.ai._resolve_api_key` 一处做这件事。

脱敏
    `mask()` 只露头尾各几位，且**总长度固定** —— 露出真实长度等于告诉别人
    试错空间有多大。日志、状态栏、异常信息里只许出现脱敏值。
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import threading
from pathlib import Path
from typing import Optional, Tuple

from data.paths import pet_home, pet_path

#: keyring 的 service 名（条目名按服务商主机名取，见 `entry_for_base_url`）。
SERVICE = "pet_demo_ai"

#: 配置值里标记「密钥在系统密钥库」的前缀。
#: 只认这个前缀，不认裸名字 —— 否则用户手写 `api_key_ref = "sk-xxx"`
#: 会被当成条目名，把密钥绕回配置里。
REF_PREFIX = "keyring:"

#: DPAPI 回退文件的存放位置（数据根内，随「导出全部数据」一起被用户带走）。
DPAPI_FILE = "secure_keys.bin"

#: 条目名白名单 —— 同时挡住路径穿越（`../../x`）和奇怪字符。
_ENTRY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: 脱敏后保留的头尾位数。头 3 / 尾 4 足够用户认出「是不是那把钥匙」，
#: 又不足以 reconstruct。
_MASK_HEAD = 3
_MASK_TAIL = 4

_LOCK = threading.RLock()

#: 后端探测结果缓存（None = 还没探过）。装没装 keyring 不会在进程生命周期里变。
_backend_cache: Optional[str] = None


# ------------------------------------------------------------ 条目名


def entry_for_base_url(base_url: str) -> str:
    """按接口地址推导条目名 —— 同一把钥匙一个名字，换服务商不打架。

    `https://api.deepseek.com/v1` → `api.deepseek.com`。
    推导不出来的（空地址 / IP）退回 `default`：宁可几个服务商共用一个名字，
    也不要因为名字不确定就把密钥写进配置。
    """
    raw = str(base_url or "").strip()
    host = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", raw)
    host = host.split("/", 1)[0].split(":", 1)[0].strip().lower()
    host = re.sub(r"[^a-z0-9.-]", "", host)
    if not host or not _ENTRY_RE.match(host):
        return "default"
    return host


def valid_entry(entry: str) -> bool:
    return bool(_ENTRY_RE.match(str(entry or "")))


def entry_of(ref: str) -> str:
    """`keyring:foo` → `foo`；裸名字原样返回（宽容，读路径上好用）。"""
    raw = str(ref or "").strip()
    if raw.startswith(REF_PREFIX):
        raw = raw[len(REF_PREFIX):]
    return raw.strip()


def ref_for(entry: str) -> str:
    """`foo` → `keyring:foo`（写进配置的就是这个）。"""
    return REF_PREFIX + entry_of(entry)


# ------------------------------------------------------------ 后端探测


def backend_name() -> str:
    """当前可用的后端名：`keyring` / `dpapi` / `none`。"""
    global _backend_cache
    with _LOCK:
        if _backend_cache is None:
            _backend_cache = _detect_backend()
        return _backend_cache


def available() -> bool:
    return backend_name() != "none"


def _detect_backend() -> str:
    if _keyring_module() is not None:
        return "keyring"
    if _dpapi_supported():
        return "dpapi"
    return "none"


def _keyring_module():
    """能导入、且选得出后端才认。`import keyring` 成功但没装任何后端时
    `get_keyring()` 会抛 `NoKeyringError` —— 那跟没装是一样的。"""
    try:
        import keyring
        import keyring.errors
    except Exception:  # noqa: BLE001 —— 没装 / 装坏了都走 DPAPI 回退
        return None
    try:
        if keyring.get_keyring() is None:
            return None
    except Exception:  # noqa: BLE001
        return None
    return keyring


def _dpapi_supported() -> bool:
    if os.name != "nt":
        return False
    try:
        return hasattr(ctypes.WinDLL("crypt32"), "CryptProtectData")
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------ 公开 API


def store_key(entry: str, secret: str) -> Tuple[bool, str]:
    """写入 / 覆盖一个条目。返回 `(成功, 给人看的一句话)`。"""
    name = entry_of(entry)
    if not valid_entry(name):
        return False, f"条目名不合法：{name!r}（只允许字母数字与 . _ -，≤64 字符）"
    secret = str(secret or "")
    if not secret:
        return False, "密钥为空，没有可保存的内容"
    backend = backend_name()
    if backend == "none":
        return False, "系统密钥库不可用（既没有 keyring，也没有 DPAPI）"
    try:
        if backend == "keyring":
            _keyring_module().set_password(SERVICE, name, secret)
        else:
            _dpapi_write(name, secret)
    except Exception as e:  # noqa: BLE001 —— 后端报错要说清楚，不能让调用方猜
        return False, f"保存到系统密钥库失败：{type(e).__name__}: {e}"
    return True, f"已保存到系统密钥库（{backend}，条目 {name}）"


def load_key(ref: str) -> str:
    """取密钥。取不到（没存 / 后端不可用 / 解密失败）一律返回空串。

    **不抛异常**：调用方（AI 链路）要的是「有一把钥匙或没有」，
    不是一个堆栈。失败原因由 `status()` 给界面看。
    """
    name = entry_of(ref)
    if not name:
        return ""
    backend = backend_name()
    if backend == "none":
        return ""
    try:
        if backend == "keyring":
            value = _keyring_module().get_password(SERVICE, name)
            return str(value) if value else ""
        return _dpapi_read(name)
    except Exception:  # noqa: BLE001
        return ""


def has_key(ref: str) -> bool:
    """条目是否存在（不返回值，供界面显示「已保存」）。"""
    return bool(load_key(ref))


def delete_key(ref: str) -> Tuple[bool, str]:
    """删掉一个条目。本来就不在也返回成功（幂等，UI 不必先查再删）。"""
    name = entry_of(ref)
    if not name:
        return False, "条目名为空"
    backend = backend_name()
    if backend == "none":
        return False, "系统密钥库不可用"
    try:
        if backend == "keyring":
            _keyring_module().delete_password(SERVICE, name)
        else:
            _dpapi_delete(name)
    except Exception as e:  # noqa: BLE001
        return False, f"从系统密钥库删除失败：{type(e).__name__}: {e}"
    return True, f"已从系统密钥库删除（条目 {name}）"


def mask(secret: str) -> str:
    """脱敏：只露头尾，**总长度固定** —— 真实长度本身就是信息。

    空串给一句明确的话，而不是返回空串：界面上「--」会被读成「加载失败」，
    而这里想说的是「还没有密钥」。
    """
    raw = str(secret or "")
    if not raw:
        return "（未设置）"
    if len(raw) <= _MASK_HEAD + _MASK_TAIL:
        # 太短不留头尾，全遮住 —— 露出 4 位里的 2 位没有辨识度，只有泄露
        return "•" * 8
    return f"{raw[:_MASK_HEAD]}{'•' * 8}{raw[-_MASK_TAIL:]}"


def status() -> str:
    """一句「密钥存在哪」的现状说明（界面直接显示）。"""
    backend = backend_name()
    if backend == "keyring":
        return "已接入系统密钥库（keyring，由操作系统按当前用户保管）"
    if backend == "dpapi":
        return "已接入系统密钥库（Windows DPAPI 加密存储，按当前用户隔离）"
    return "系统密钥库不可用：密钥只能明文保存在配置文件里（不推荐）"


# ------------------------------------------------------------ DPAPI 后端


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _DATA_BLOB:
    return _DATA_BLOB(len(data), ctypes.cast(
        ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_char)))


def _dpapi_protect(plain: bytes) -> bytes:
    """`CryptProtectData` —— 按当前用户加密，换用户/换机器都解不开。"""
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    out = _DATA_BLOB()
    # CRYPTPROTECT_UI_FORBIDDEN：绝不弹窗。弹窗会让后台线程卡住。
    ok = crypt32.CryptProtectData(
        ctypes.byref(_blob(plain)), None, None, None, None, 0x1,
        ctypes.byref(out))
    if not ok:
        raise OSError(f"CryptProtectData 失败: {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.WinDLL("kernel32").LocalFree(out.pbData)


def _dpapi_unprotect(blob: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    out = _DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(_blob(blob)), None, None, None, None, 0x1,
        ctypes.byref(out))
    if not ok:
        raise OSError(f"CryptUnprotectData 失败: {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.WinDLL("kernel32").LocalFree(out.pbData)


def _dpapi_path() -> Path:
    return pet_path(DPAPI_FILE)


def _dpapi_read_all() -> dict:
    path = _dpapi_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 —— 文件坏了就当空的，别让整个功能不可用
        return {}
    entries = raw.get("entries") if isinstance(raw, dict) else None
    return entries if isinstance(entries, dict) else {}


def _dpapi_write_all(entries: dict) -> None:
    path = _dpapi_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"version": 1, "entries": entries},
                         ensure_ascii=False)
    # 先写临时文件再替换：半路崩了也不会留下一个解不开的「密钥库」
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _dpapi_write(name: str, secret: str) -> None:
    with _LOCK:
        entries = _dpapi_read_all()
        entries[name] = base64.b64encode(_dpapi_protect(
            secret.encode("utf-8"))).decode("ascii")
        _dpapi_write_all(entries)


def _dpapi_read(name: str) -> str:
    with _LOCK:
        blob = _dpapi_read_all().get(name)
    if not blob:
        return ""
    try:
        plain = _dpapi_unprotect(base64.b64decode(str(blob)))
    except Exception:  # noqa: BLE001 —— 换用户/换机器解不开 → 当作没有这把钥匙
        return ""
    return plain.decode("utf-8", "replace")


def _dpapi_delete(name: str) -> None:
    with _LOCK:
        entries = _dpapi_read_all()
        if name in entries:
            del entries[name]
            _dpapi_write_all(entries)
