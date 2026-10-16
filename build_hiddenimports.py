# -*- coding: utf-8 -*-
"""打包依赖自动扫描（对应执行框架 §5 T4，修复宿主缺陷 C4）。

背景
----
`PetDemo.spec` 的 `hiddenimports` 原先是**手工维护**的：每新增一个被动态导入的模块
（插件、provider、tool），都必须记得回来补一行，否则打包出的 exe 运行时
`ModuleNotFoundError`，而开发环境一切正常 —— 这类故障最难排查。

本模块把这些模块**扫出来**，`PetDemo.spec` 只需 `BASE_IMPORTS + scan_hiddenimports()`。

扫描对象
--------
1. `engine/`  —— AI 核心层（被插件动态导入，PyInstaller 静态分析看不到）
2. `native/`  —— 系统代理层（同上）
3. `tools/`   —— 既有工具实现（插件按名加载）
4. `extensions/` —— 插件外壳（插件按文件路径加载，其内部 import 不可静态发现）
5. `presentation/` —— 交互层。**必须包含**：插件里有
   `from presentation.ai_panel import AIPanel` 这类**延迟导入**，
   而 PyInstaller 的静态分析只从 `main.py` 出发，看不到插件的导入边。

   > 踩过的坑：最初 SCAN_DIRS 里没有 `presentation`，
   > 结果 `presentation.ai_settings_dialog`（在 `plugin._open_settings()` 里
   > 函数内导入）没进 hiddenimports —— 开发环境一切正常，
   > 打包后一点「设置」就 `ModuleNotFoundError`。
   > **新增顶层包时，记得同步这里。**

扫描规则
--------
- 递归收集 `*.py`，跳过 `__pycache__`、`build`、`dist`、以 `_` 开头的私有模块可保留
  （它们可能被同包模块导入，代价只是包体略大）。
- 路径转点号模块名：`engine/ai/providers/openai_compat.py` → `engine.ai.providers.openai_compat`。
- 额外解析源码里 `importlib.import_module("x")` / `__import__("x")` 的字符串字面量，
  以及 `sys.path.insert` 后动态导入的模块名，兜住扫描不到的漏网之鱼。

用法
----
```bash
python build_hiddenimports.py            # 打印扫描结果（自检用）
python build_hiddenimports.py --json     # 输出 JSON，便于脚本消费
```

在 `PetDemo.spec` 中：

```python
from build_hiddenimports import scan_hiddenimports
hiddenimports = BASE_IMPORTS + scan_hiddenimports()
```
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Iterable, List, Set

# 项目根目录（本文件所在目录）
ROOT = Path(__file__).resolve().parent

# 需要扫描的顶层包
# ⚠ 新增顶层包（被插件延迟导入的）时必须同步这里，否则打包后才会暴露
SCAN_DIRS = ("engine", "native", "tools", "extensions", "presentation", "data")

# 扫描时要跳过的目录名
SKIP_DIRS = {"__pycache__", "build", "dist", ".git", ".pytest_cache", "spikes", "tests"}


def _iter_py_files(root: Path) -> Iterable[Path]:
    """递归产出 root 下所有 .py 文件，跳过 SKIP_DIRS。"""
    if not root.is_dir():
        return
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _module_name(py_file: Path) -> str:
    """把 .py 路径转成点号模块名。__init__.py 归到包名本身。"""
    rel = py_file.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _dynamic_imports(py_file: Path) -> Set[str]:
    """解析源码里动态导入的字符串字面量。

    覆盖 `importlib.import_module("x.y")`、`__import__("x")`、
    `importlib.util.spec_from_file_location(...)` 之外最常见的两种写法。
    解析失败（语法错误 / 编码问题）时静默跳过，不阻断打包。
    """
    found: Set[str] = set()
    try:
        source = py_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return found

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return found

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = ""
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr

        if name not in ("import_module", "__import__"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.add(first.value)

    return found


def scan_hiddenimports(verbose: bool = False) -> List[str]:
    """扫描并返回排序去重后的 hiddenimports 列表。"""
    modules: Set[str] = set()
    dynamic: Set[str] = set()

    for dir_name in SCAN_DIRS:
        for py_file in _iter_py_files(ROOT / dir_name):
            mod = _module_name(py_file)
            if mod:
                modules.add(mod)
            dynamic.update(_dynamic_imports(py_file))

    # 动态导入里属于本项目的，补进列表；外部第三方（requests 等）由 BASE_IMPORTS 管
    for mod in dynamic:
        top = mod.split(".")[0]
        if top in SCAN_DIRS:
            modules.add(mod)

    result = sorted(modules)
    if verbose:
        print(f"[scan_hiddenimports] 扫描 {len(result)} 个模块：", file=sys.stderr)
        for m in result:
            print(f"  - {m}", file=sys.stderr)
    return result


def main() -> int:
    args = sys.argv[1:]
    modules = scan_hiddenimports(verbose="--json" not in args)
    if "--json" in args:
        print(json.dumps(modules, ensure_ascii=False, indent=2))
    else:
        print(f"\n共 {len(modules)} 个模块可加入 hiddenimports。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
