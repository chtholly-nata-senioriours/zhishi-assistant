#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""开发启动器（免安装通道）

本仓库自带了一份便携式 Python 依赖（`Lib/`、`Scripts/`），但**目录内没有 python.exe**。
本脚本负责把这份依赖挂到当前解释器上，从而免去 pip 安装。

本仓库的依赖被装进了**两个不同的目录**（这不是笔误，是实测结论）：
    - `Lib/site-packages/`  → PySide6 / pynput / pywin32 / pytest
    - `Lib/`                → requests / urllib3 / Crypto / certifi / idna / charset_normalizer

本脚本做四件事：
    1. 把 `Lib` 与 `Lib/site-packages` 都加入 `sys.path`
    2. 为 pywin32 注册 DLL 目录 —— Python 3.8+ 不再通过 PATH 查找扩展模块依赖，
       不注册就会出现 `ImportError: DLL load failed while importing win32gui`
    3. 把 `win32` / `win32/lib` / `Pythonwin` 加入 `sys.path`（等价于 pywin32.pth）
    4. 把项目根目录加入 `sys.path`（顶层模块以 `import event_bus` 形式导入）

用法（在项目根目录执行）：
    python dev_bootstrap.py                      # 启动知时助手（等价 python main.py）
    python dev_bootstrap.py check_project.py     # 跑项目自检
    python dev_bootstrap.py -m pytest tests -q   # 跑测试套件

若你使用独立 venv（`pip install -r requirements.txt`），则不需要本脚本，
直接 `python main.py` 即可。
"""
import os
import sys
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIB = ROOT / "Lib"
SITE = LIB / "site-packages"

# 必须持有 add_dll_directory 返回的句柄，否则会被 GC 回收、
# 目录随即从 DLL 搜索路径中移除（这是 CPython 的已知行为）。
_DLL_HANDLES = []


def bootstrap() -> None:
    """把项目自带的 Lib/ 依赖挂到当前解释器上。"""
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    # Lib/ 与 Lib/site-packages/ 是两批依赖的落点，缺一不可
    if LIB.is_dir():
        sys.path.insert(0, str(LIB))
    if not SITE.is_dir():
        return

    sys.path.insert(0, str(SITE))

    dll_dir = SITE / "pywin32_system32"
    if dll_dir.is_dir() and hasattr(os, "add_dll_directory"):
        _DLL_HANDLES.append(os.add_dll_directory(str(dll_dir)))

    for sub in ("win32", "win32/lib", "Pythonwin"):
        p = SITE / sub
        if p.is_dir():
            sys.path.insert(0, str(p))


def main() -> int:
    bootstrap()
    args = sys.argv[1:]
    if not args:
        args = ["main.py"]

    if args[0] == "-m":
        if len(args) < 2:
            print("用法: python dev_bootstrap.py -m <module> [args...]")
            return 2
        sys.argv = args[1:]
        runpy.run_module(args[1], run_name="__main__")
        return 0

    sys.argv = args
    # 与 `python <script>` 的语义对齐：把脚本所在目录也加入 sys.path。
    # runpy.run_path 不会做这件事，导致 spikes/*.py 里的 `import _common` 失败。
    script = Path(args[0]).resolve()
    if script.parent != ROOT and str(script.parent) not in sys.path:
        sys.path.insert(0, str(script.parent))
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
