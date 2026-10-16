#!/usr/bin/env python
"""快速项目检查脚本 - 检查代码完整性、依赖和基本风险"""

import sys, os, json
from pathlib import Path

def check_imports():
    """检查关键模块是否可导入"""
    modules = ['event_bus', 'engine.state_machine', 'data.config_manager', 'tools.timer_tool']
    failed = []
    for mod in modules:
        try:
            __import__(mod)
            print(f"✓ {mod}")
        except ImportError as e:
            failed.append(f"✗ {mod}: {e}")
    return failed

def check_config():
    """检查配置文件存在性"""
    config_file = Path("config.default.json")
    if config_file.exists():
        try:
            with open(config_file) as f:
                cfg = json.load(f)
                print(f"✓ config.default.json (version: {cfg.get('version')})")
                return []
        except json.JSONDecodeError as e:
            return [f"✗ config.default.json: 格式错误 - {e}"]
    return ["✗ config.default.json: 文件不存在"]

def check_data_root():
    """检查用户数据根可写 —— 配置 / 日志 / 两个库 / 缓存全落在那里。

    2026-10-15：原来这里查的是「宠物精灵图资源」，随精灵图一起删了。
    换成这条更有用的：数据根不可写时，程序每次启动都会在保存配置时炸，
    而用户看到的现象只是「设置总是保存不了」—— 提前查出来更值。
    （不实际创建文件：`os.access` 只问权限，不落任何东西。）
    """
    from data.paths import pet_home

    root = pet_home()
    if not root.exists():
        parent_ok = root.parent.exists()
        print(f"· 数据目录尚未创建：{root}（首次运行自动建立）")
        return [] if parent_ok else [f"✗ 用户主目录不存在：{root.parent}"]
    writable = os.access(root, os.W_OK)
    print(f"{'✓' if writable else '✗'} 数据目录{'可写' if writable else '不可写'}：{root}")
    return [] if writable else [f"✗ 数据目录不可写：{root}"]

def check_main():
    """检查main.py可执行性"""
    main_file = Path("main.py")
    if main_file.exists():
        print("✓ main.py 存在")
        return []
    return ["✗ main.py 不存在"]

def main():
    os.chdir(Path(__file__).parent)
    print("=" * 50)
    print("知时助手项目快速检查")
    print("=" * 50)
    
    errors = []
    print("\n[1] 配置检查:")
    errors.extend(check_config())
    
    print("\n[2] 入口检查:")
    errors.extend(check_main())
    
    print("\n[3] 数据根检查:")
    errors.extend(check_data_root())
    
    print("\n[4] 模块检查:")
    errors.extend(check_imports())
    
    print("\n" + "=" * 50)
    if errors:
        print("发现问题:")
        for err in errors:
            print(f"  {err}")
        return 1
    else:
        print("✓ 所有检查通过! 可运行 `python main.py`")
        return 0

if __name__ == "__main__":
    sys.exit(main())
