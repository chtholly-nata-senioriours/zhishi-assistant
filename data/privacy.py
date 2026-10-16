# -*- coding: utf-8 -*-
"""本机数据的清单 / 导出 / 清空 —— 「隐私与数据」页的后端。

## 为什么单独一个模块

用户要的不是一句「我们重视您的隐私」，而是**三件能自己做主的动作**：
看清本机存了什么、把它打包带走、把它删掉。这三件事都必须真的作用到
`~/.pet_demo`（见 `data/paths.py` —— 数据根的唯一来源），而不是只改界面状态。

于是这里只做**不带 Qt 的逻辑**：枚举、统计大小、打包、删除。
界面（`presentation/control_center.py::PrivacyPage`）只负责提问与展示结果。
分工的好处是这套逻辑能用测试直接覆盖 —— 不弹一个窗口也能验「删对了没有」。

## 关键实现决定

1. **路径在调用时求值，不做常量。** 数据根可被 `PET_DEMO_HOME` 覆盖，
   且刻意不做模块级缓存（见 `paths.pet_home()` 的注释）。写常量等于
   把根钉死，测试整体挪窝的能力就没了。
2. **数据库用 `sqlite3` 的 backup API 打包**，不原样拷 `-wal` / `-shm`。
   原样拷三件套在「应用正开着」时可能拿到不一致的快照；backup 出来的
   是一个干净、自包含的库，且不需要应用先退出。
3. **能在运行时安全清空的就走活实例的 API**（配置重置 / 插件 clear /
   日志清空），**不能的才关句柄删文件**（`ai.db` 关掉共享单例，
   下次访问会按 schema 重建）。直接删一个还被开着的库文件，
   在 Windows 上只会得到 `PermissionError`。
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from data.paths import pet_home, pet_path

#: 导出的 zip 里附一份说明 —— 用户三个月后解开这个包，看到的不该是一堆裸文件。
_EXPORT_NOTE = """知时助手 · 本机数据导出
导出时间：{when}
数据目录：{home}

里面是什么
    user_config.json   设置与偏好（含 AI 服务地址、模型与 API 密钥）
    ai.db              与 AI 的会话历史、提问与回答
    activity.db        活动记录：前台应用名、类别、停留时长
    logs/              运行日志（排障用）
    cache/             界面图标缓存（删了会自动重建）
    README.txt         本文件

注意
    API 密钥只保存在本机，不会随任何请求发送到第三方。
    这个包里含有它 —— 分享这个 zip 前请先删掉 user_config.json。
"""


@dataclass(frozen=True)
class DataEntry:
    """一类本机数据。`paths` 是它可能占用的全部文件（含 sqlite 旁车与备份）。"""

    key: str
    label: str
    detail: str
    paths: tuple[Path, ...]
    sensitive: bool = False

    def size(self) -> int:
        return sum(_path_size(p) for p in self.paths)


def _db_paths(stem: str) -> tuple[Path, ...]:
    """库文件连同它的 WAL / SHM 旁车一起算 —— 只删主文件会留下几 MB 孤儿。"""
    return (pet_path(f"{stem}.db"), pet_path(f"{stem}.db-wal"),
            pet_path(f"{stem}.db-shm"))


def _config_paths() -> tuple[Path, ...]:
    home = pet_home()
    if not home.is_dir():
        return (pet_path("user_config.json"),)
    found = [home / "user_config.json"]
    found += sorted(home.glob("user_config.json.bak-*"))
    return tuple(found)


def _legacy_paths() -> tuple[Path, ...]:
    """便签 / 快捷启动随 v1.7.0 一起移除，这两个文件已无人读写。

    仍然列出来：老用户磁盘上还躺着它们，而用户有权知道自己机器上
    有哪些属于这个程序的数据。
    """
    return tuple(p for p in (pet_path("notes.json"), pet_path("quick_launch.json"))
                 if p.exists())


def _key_storage_note() -> str:
    """如实说明 API Key 存在哪 —— 隐私页说的每一句都要能被代码兑现。

    v1.8.0 起密钥可搬进系统密钥库（见 `data/key_store.py`）。这里不写
    「已加密」这种含糊话，而是按当前配置指出**实际位置**：
    用户从界面上就能核对这句话对不对。
    """
    try:
        from data.config_manager import config_manager

        ref = str(config_manager.get("ai.api_key_ref", "") or "")
        has_plain = bool(str(config_manager.get("ai.api_key", "") or ""))
    except Exception:  # noqa: BLE001 —— 读不到配置就说不知道，别猜
        return ""
    if ref.startswith("keyring:"):
        return "API Key 保存在系统密钥库里，配置文件只留一个引用。"
    if has_plain:
        return "API Key 目前明文保存在配置文件里 —— 可在「AI 服务」页把它搬进系统密钥库。"
    return ""


def entries() -> list[DataEntry]:
    """本机数据的完整清单（顺序即「隐私与数据」页的展示顺序）。"""
    key_note = _key_storage_note()
    config_detail = "AI 服务地址、模型、界面与采集开关等全部设置。"
    if key_note:
        config_detail = f"{config_detail}\n{key_note}"
    return [
        DataEntry(
            "config", "设置与偏好",
            config_detail,
            _config_paths(), sensitive=True),
        DataEntry(
            "ai_sessions", "AI 会话历史",
            "你与 AI 的提问、回答，以及自建的预设。",
            _db_paths("ai"), sensitive=True),
        DataEntry(
            "activity", "活动记录",
            "前台应用名、类别与停留时长 —— 不含窗口标题、按键与剪贴板。",
            _db_paths("activity")),
        DataEntry(
            "logs", "运行日志",
            "用于排查问题的运行记录。",
            (pet_path("logs"),)),
        DataEntry(
            "cache", "界面缓存",
            "图标渲染缓存，删除后下次使用会自动重建。",
            (pet_path("cache"),)),
        DataEntry(
            "legacy", "旧版本遗留数据",
            "便签与快捷启动已随新版移除，这些文件不再被读写。",
            _legacy_paths()),
    ]


def find(key: str) -> DataEntry | None:
    for entry in entries():
        if entry.key == key:
            return entry
    return None


# ---------------------------------------------------------------- 体积


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def human_size(n: int) -> str:
    """字节数 → 人类可读。刻意不进 UI 层：各处都要同一个口径。"""
    step = 1024.0
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < step or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= step
    return f"{value:.1f} GB"


def total_size() -> int:
    return sum(e.size() for e in entries())


# ---------------------------------------------------------------- 导出


def _backup_db(src: Path, dest: Path) -> bool:
    """把 sqlite 库打包成干净的单文件副本。失败返回 False（调用方回退到原样拷）。"""
    if not src.exists():
        return False
    source = None
    target = None
    try:
        source = sqlite3.connect(str(src))
        target = sqlite3.connect(str(dest))
        source.backup(target)
        return True
    except Exception:  # noqa: BLE001 —— 打包失败要能回退，不能把用户挡在门外
        return False
    finally:
        for conn in (source, target):
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass


def _is_sidecar(path: Path) -> bool:
    """sqlite 的 WAL / SHM 旁车。

    刻意用 `name.endswith` 而不是 `suffix`：`Path("ai.db-wal").suffix`
    是 **`.db-wal`**（最后一个点之后的一切），拿 `-wal` 去比永远不相等 ——
    真写出来时旁边还有个 `-shm` 会被原样拷进 zip，而它不能被单独打开。
    """
    return path.name.endswith(("-wal", "-shm"))


def _selected_rels(home: Path, keys) -> list[Path] | None:
    """要打包哪些文件（相对 `home`）。`keys=None` 表示整个数据目录。

    单类导出与全量导出走**同一条打包通道**，差别只在这一步选谁 ——
    另写一个「只拷一个文件」的分支，两头迟早会走偏。
    """
    if keys is None:
        return None
    picked: set[Path] = set()
    for key in keys:
        entry = find(key)
        if entry is None:
            continue
        for p in entry.paths:
            if p.is_file() and home in p.parents and not _is_sidecar(p):
                picked.add(p.relative_to(home))
    return sorted(picked)


def export_data(dest_dir: Path, keys=None) -> tuple[bool, str, Path | None]:
    """把数据打包成 zip 写到 `dest_dir`。

    `keys=None` 导出全部；否则只导出这几类数据（key 见 `entries()`）。
    返回 `(是否成功, 给人看的一句话, zip 路径)`。**任何一步失败都讲清楚
    卡在哪** —— 导出是用户拿走自己数据的唯一通道，静默失败等于骗人。
    """
    home = pet_home()
    if not home.is_dir():
        return False, f"数据目录不存在：{home}", None
    if not dest_dir.is_dir():
        return False, f"目标目录不存在：{dest_dir}", None

    picked = _selected_rels(home, keys)
    if picked is not None and not picked:
        return False, "还没有数据可导出。", None

    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = dest_dir / f"知时助手数据导出_{stamp}.zip"
    copied = 0

    def _walk() -> list[Path]:
        """要过一遍 zip 的相对路径（全量时现场枚举目录，顺手排掉旁车）。"""
        if picked is not None:
            return picked
        found = []
        for path in sorted(home.rglob("*")):
            if path == target or not path.is_file():
                continue          # 别把自己写进去
            if _is_sidecar(path):
                continue          # 由下面的 backup 统一处理
            found.append(path.relative_to(home))
        return found

    try:
        with tempfile.TemporaryDirectory() as td, \
                zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in _walk():
                src = home / rel
                if not src.is_file():
                    continue
                if src.suffix == ".db":
                    # 落到临时目录而不是 cwd —— 备份文件不该出现在用户眼前
                    fresh = Path(td) / f"{src.stem}.db"
                    if _backup_db(src, fresh):
                        zf.write(fresh, str(rel))
                        copied += 1
                        continue
                    # backup 不成就原样拷 —— 有总比没有强
                zf.write(src, str(rel))
                copied += 1

            zf.writestr("README.txt", _EXPORT_NOTE.format(
                when=time.strftime("%Y-%m-%d %H:%M:%S"), home=home))
    except Exception as e:  # noqa: BLE001
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return False, f"导出失败：{type(e).__name__}: {e}", None

    if copied == 0:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return False, "还没有数据可导出。", None

    return True, f"已导出 {copied} 个文件（{human_size(target.stat().st_size)}）", target


# ---------------------------------------------------------------- 清空


def _remove(paths) -> tuple[int, int]:
    """删文件/目录，返回 `(成功数, 字节数)`。单个失败不中断 —— 后面继续删。"""
    removed, freed = 0, 0
    for path in paths:
        size = _path_size(path)
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            else:
                continue
            removed += 1
            freed += size
        except OSError:
            continue
    return removed, freed


def clear_entry(key: str, app=None) -> tuple[bool, str]:
    """清空一类数据。返回 `(是否成功, 给人看的一句话)`。

    `app` 是宿主实例（鸭子类型）—— 需要时向活动插件借活句柄。
    Preview 脚本与测试可以传 None，这时走「关句柄删文件」的通用路径。
    """
    entry = find(key)
    if entry is None:
        return False, f"未知的数据类型：{key}"

    if key == "config":
        from data.config_manager import config_manager
        config_manager.reset_to_default()
        removed, freed = _remove(home_bak_files())
        return True, ("已恢复默认设置（AI 密钥也一并清除）。"
                      + (f"顺手删掉 {removed} 个旧配置备份。" if removed else ""))

    if key == "ai_sessions":
        # 共享单例持有着连接 —— 先关，删完下次访问会按 schema 重建。
        from engine.ai.store import close_shared_store
        try:
            close_shared_store()
        except Exception:  # noqa: BLE001
            pass
        removed, freed = _remove(entry.paths)
        if removed == 0:
            return False, "会话库文件被占用，关掉程序后再试。"
        return True, f"已删除 AI 会话历史，释放 {human_size(freed)}。"

    if key == "activity":
        # 优先借插件的活句柄清空（它自己还持着连接，直接删文件会撞权限）。
        plugin = _activity_plugin(app)
        if plugin is not None and hasattr(plugin, "clear_data"):
            try:
                removed = int(plugin.clear_data() or 0)
            except Exception as e:  # noqa: BLE001
                return False, f"清空活动记录失败：{type(e).__name__}: {e}"
            # 主库**不删**（插件还开着它）—— 只清 WAL/SHM 旁车，
            # 否则删掉正在用的文件，Windows 上只会得到 PermissionError。
            sidecars = tuple(p for p in entry.paths
                             if _is_sidecar(p))
            _remove(sidecars)
            return True, f"已清空活动记录（{removed} 条分段）。"
        removed, freed = _remove(entry.paths)
        if removed == 0:
            return False, "活动库文件被占用，关掉程序后再试。"
        return True, f"已删除活动记录，释放 {human_size(freed)}。"

    if key == "logs":
        from data.log_manager import log_manager
        try:
            log_manager.clear_logs()
        except Exception as e:  # noqa: BLE001
            return False, f"清空日志失败：{type(e).__name__}: {e}"
        return True, "已清空运行日志。"

    if key == "cache":
        removed, freed = _remove((pet_path("cache"),))
        if removed == 0:
            return False, "缓存目录被占用，关掉程序后再试。"
        return True, f"已清空界面缓存，释放 {human_size(freed)}（会自动重建）。"

    if key == "legacy":
        if not entry.paths:
            return True, "没有旧版本遗留数据。"
        removed, freed = _remove(entry.paths)
        return True, f"已删除 {removed} 个旧版本遗留文件，释放 {human_size(freed)}。"

    return False, f"暂不支持清空「{entry.label}」"


def home_bak_files() -> tuple[Path, ...]:
    """配置的历史备份（`user_config.json.bak-*`）—— 与配置条目分开删，报告要分开说。"""
    home = pet_home()
    if not home.is_dir():
        return ()
    return tuple(sorted(home.glob("user_config.json.bak-*")))


def _activity_plugin(app):
    pm = getattr(app, "plugin_manager", None) if app is not None else None
    getter = getattr(pm, "get_plugin", None) if pm is not None else None
    if not callable(getter):
        return None
    try:
        return getter("activity_advisor")
    except Exception:  # noqa: BLE001
        return None
