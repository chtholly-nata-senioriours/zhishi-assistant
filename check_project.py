#!/usr/bin/env python
"""快速项目检查脚本 - 检查代码完整性、依赖和基本风险"""

import sys, os, json
from pathlib import Path

def check_imports():
    """检查关键模块是否可导入"""
    modules = ['event_bus', 'engine.state_machine', 'data.config_manager', 'tools.quick_launch']
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

def check_assets():
    """检查资源文件"""
    assets_dir = Path("presentation/assets/models/default")
    if assets_dir.exists():
        required = ['pet.jpg', 'idle.png', 'sleep.png', 'wave.png']
        missing = [f for f in required if not (assets_dir / f).exists()]
        if missing:
            return [f"✗ 缺失精灵图资源: {missing}"]
        print(f"✓ 精灵图资源完整")
        return []
    return ["✗ 默认宠物资源目录不存在"]

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
    print("桌宠项目快速检查")
    print("=" * 50)
    
    errors = []
    print("\n[1] 配置检查:")
    errors.extend(check_config())
    
    print("\n[2] 入口检查:")
    errors.extend(check_main())
    
    print("\n[3] 资源检查:")
    errors.extend(check_assets())
    
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
