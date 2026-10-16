# -*- coding: utf-8 -*-
"""发版冒烟：exe 真的能起来、而且起的是**这一版**。

为什么要有脚本，而不是 Bash 一行流
    以前每次发版都现场拼一行流，结果每次都踩同样的两个坑（AGENTS.md §4.13 有记录）：
      ① `BEFORE=$(wc -l < log) && ./exe &` 会把**整条链**丢进子 shell，
         父 shell 的 `BEFORE` 是空的 → `tail -n +1` 把整个日志打出来；
      ② 列表推导里写错变量名 → `NameError` → taskkill 静默没执行
         → **`taskkill` 静默没执行**，exe 一直挂着。
    脚本把这些固化成代码，顺便把「版本行到底在哪个流」这件事一次查清。

三条判据（不可互相替代）
    ① 存活 ≥16s（启动序列 ~5s，留足余量）；
    ② 输出里出现 `版本: x.y.z`，且 x.y.z == `config.default.json` 的 version；
    ③ `app.log` 新增行里有**完整启动序列**，且零 `[ERROR]`。

    ⚠ 「启动序列完整」**证明不了窗口存在** —— `app.log` 到「热键已注册」就停，
    之后进 Qt 事件循环不再打日志。**窗口存在与否归 `exe_window_check.py` 管**，
    两者必须都跑。

⚠ 版本行在 **stderr**，不在 stdout
    `data.config_manager` 用的是 `logging.getLogger(__name__)`，
    它的记录走 root 的 `StreamHandler`，而 `StreamHandler` **默认输出到 stderr**。
    实测 v1.5.0 时记录的「版本行在 stdout」**不够准确** —— 两个流都要收。

用法（在项目根目录）
    python dev_bootstrap.py spikes/smoke_exe.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "知时助手" / "知时助手.exe"
LOG = Path.home() / ".pet_demo" / "logs" / "app.log"

#: 存活判据（秒）。启动序列实测 ~5s，留足余量。
ALIVE_S = 17

#: 完整启动序列的关键行（顺序即实际顺序，但只查「在不在」）。
SEQ = ["AI 助手插件已加载", "系统托盘已启动", "键盘控制器已预热",
       "剪贴板已预热", "AI 面板已预热", "热键已注册"]


def expected_version() -> str:
    """版本号的唯一来源 —— 与 `config.default.json` 对齐，不写死。"""
    try:
        cfg = json.loads((ROOT / "config.default.json").read_text(encoding="utf-8"))
        return str(cfg.get("version") or "")
    except Exception:  # noqa: BLE001
        return ""


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def main() -> int:
    if not EXE.exists():
        print(f"!! 找不到 exe：{EXE}")
        return 2

    version = expected_version()
    if not version:
        print("!! 读不到 config.default.json 的 version")
        return 2

    OUT = Path(tempfile.mkstemp(prefix="smoke_out_", suffix=".txt")[1])
    ERR = Path(tempfile.mkstemp(prefix="smoke_err_", suffix=".txt")[1])
    before = _read(LOG).splitlines()

    try:
        with open(OUT, "w", encoding="utf-8", errors="replace") as fo, \
                open(ERR, "w", encoding="utf-8", errors="replace") as fe:
            proc = subprocess.Popen([str(EXE)], stdout=fo, stderr=fe, cwd=str(EXE.parent))
            print(f"已启动 pid={proc.pid}，等 {ALIVE_S}s ...")
            t0 = time.time()
            while time.time() - t0 < ALIVE_S:
                time.sleep(0.5)
                if proc.poll() is not None:
                    print(f"[FAIL] 进程提前退出 returncode={proc.returncode} "
                          f"(存活 {time.time() - t0:.1f}s)")
                    _kill(proc.pid)
                    return 1
            alive = time.time() - t0

        # 收尾必须 taskkill /F /T —— 孤儿会锁住 dist/.../_internal 的 DLL，
        # 让下次 `PyInstaller --clean` 报 WinError 5（见 AGENTS.md）。
        killed = _kill(proc.pid)

        stdout, stderr = _read(OUT), _read(ERR)
        after = _read(LOG).splitlines()
        new = after[len(before):]
    finally:
        for p in (OUT, ERR):
            try:
                p.unlink()
            except OSError:
                pass

    print(f"[i] 存活 {alive:.1f}s")
    print(f"[i] 清理进程: {killed[:70]}")
    print("\n--- 输出尾部（stdout+stderr）---")
    tail = (stdout.strip() + "\n" + stderr.strip()).strip().splitlines()
    for line in tail[-10:]:
        print("  " + line[:150])

    both = stdout + "\n" + stderr
    ok_alive = alive >= 16
    ok_ver = f"版本: {version}" in both
    missing = [s for s in SEQ if not any(s in l for l in new)]
    errors = [l for l in new if "[ERROR]" in l or "[CRITICAL]" in l]

    print("\n--- app.log 新增行 ---")
    for line in new[:20]:
        print("  " + line[:150])

    print()
    print(f"[{'OK' if ok_alive else 'FAIL'}] ① 存活 ≥16s: {alive:.1f}s")
    print(f"[{'OK' if ok_ver else 'FAIL'}] ② 版本行 `版本: {version}`（stdout / stderr 任一）")
    print(f"[{'OK' if not missing else 'FAIL'}] ③ 启动序列: "
          f"{'完整' if not missing else '缺 ' + str(missing)}")
    print(f"[{'OK' if not errors else 'FAIL'}] 零 ERROR: "
          f"{'无' if not errors else errors[:3]}")

    ok = ok_alive and ok_ver and not missing and not errors
    print("\nSMOKE:", "PASS" if ok else "FAIL")
    print("（窗口存在与否请另跑 spikes/exe_window_check.py —— 本脚本管不到）")
    return 0 if ok else 1


def _kill(pid: int) -> str:
    """`taskkill /F /T`。

    ⚠ 必须走 `subprocess` 的**列表形式**，不要拼 shell 字符串：
    Git Bash 会把 `/F` `/T` `/PID` 当路径转换，报「无效参数/选项 - 'F:/'」。
    """
    r = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    return (r.stdout or r.stderr).decode("gbk", errors="replace").strip()


if __name__ == "__main__":
    sys.exit(main())
