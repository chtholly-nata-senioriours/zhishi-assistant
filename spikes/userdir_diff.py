# -*- coding: utf-8 -*-
"""用户数据目录比对 —— 验证「测试不许碰用户的运行数据」。

为什么需要它
    `~/.pet_demo/` 里有配置、日志、便签、快捷启动项、会话库 `ai.db`、
    活动库 `activity.db`、图标缓存。测试一旦碰到这些路径就会**静默**写进去：
    测试全绿、内容还字节相同 —— 只有 mtime 变了。

    这不是假设。2026-10-14 用它查出来的：

        非 cache 的 mtime 变化: ['user_config.json']
        user_config.json 前: mtime=1791952484.242  sha1=4aac6d27bbfb5c68
        user_config.json 后: mtime=1791952552.462  sha1=4aac6d27bbfb5c68
                                                ↑ 内容一样，但每次跑测试都重写一遍

    根因：`data.config_manager` 是进程级单例，**被 import 的那一刻**就
    `_load_config()` → `save()`。pytest 的 fixture 要到测试执行时才跑，
    拦不住 import。修法与复现见 `data/paths.py` 与 `tests/conftest.py`。

用法（在项目根目录）
    python dev_bootstrap.py spikes/userdir_diff.py snap   before.json
    python dev_bootstrap.py -m pytest tests -q --basetemp=.pytest_tmp
    python dev_bootstrap.py spikes/userdir_diff.py snap   after.json
    python dev_bootstrap.py spikes/userdir_diff.py diff   before.json after.json

    diff 必须报 **新增 0 / 删除 0 / mtime 变 0 / 内容变 0**。
    只报「内容变 0」是不够的 —— mtime 变化本身就是泄漏的证据。

隐私
    只记录 path / mtime / size / sha1，**不打印任何文件内容**
    （用户配置里有明文密钥）。
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.paths import pet_home  # noqa: E402


def _fingerprint(p: Path):
    try:
        st = p.stat()
    except OSError:
        return None
    digest = ""
    if st.st_size <= 4 * 1024 * 1024:
        try:
            digest = hashlib.sha1(p.read_bytes()).hexdigest()[:16]
        except OSError:
            digest = "?"
    return {"mtime": round(st.st_mtime, 3), "size": st.st_size, "sha1": digest}


def snap(out_path: str) -> None:
    root = pet_home()
    data = {}
    if root.exists():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                fp = _fingerprint(p)
                if fp:
                    data[str(p.relative_to(root))] = fp
    Path(out_path).write_text(json.dumps(data, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"快照 {len(data)} 个文件（根目录 {root}）-> {out_path}")


def diff(before_path: str, after_path: str) -> int:
    before = json.loads(Path(before_path).read_text(encoding="utf-8"))
    after = json.loads(Path(after_path).read_text(encoding="utf-8"))

    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed_mtime, changed_content = [], []
    for k in sorted(set(before) & set(after)):
        if before[k]["mtime"] != after[k]["mtime"]:
            changed_mtime.append(k)
        if before[k]["sha1"] != after[k]["sha1"]:
            changed_content.append(k)

    print(f"新增 {len(added)} / 删除 {len(removed)} / "
          f"mtime 变 {len(changed_mtime)} / 内容变 {len(changed_content)}")
    for label, items in (("新增", added), ("删除", removed),
                         ("内容变", changed_content), ("仅 mtime 变", changed_mtime)):
        if items:
            print(f"\n--- {label} ---")
            for i in items[:40]:
                print("  ", i)
            if len(items) > 40:
                print(f"   ... 另有 {len(items) - 40} 项")

    leaked = len(added) + len(removed) + len(changed_mtime) + len(changed_content)
    print()
    print("RESULT: " + ("OK 测试没有碰用户数据目录" if leaked == 0
                        else f"LEAK 有 {leaked} 项被改动 —— 测试在写用户的运行数据"))
    return 0 if leaked == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("用法: userdir_diff.py snap <out.json> | diff <before.json> <after.json>")
    mode = sys.argv[1]
    if mode == "snap":
        snap(sys.argv[2])
        sys.exit(0)
    if mode == "diff":
        sys.exit(diff(sys.argv[2], sys.argv[3]))
    raise SystemExit("mode 只能是 snap / diff")
