"""配置管理单元测试"""

import sys
import json
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.config_manager import ConfigManager


def test_default_config_structure():
    """测试默认配置结构"""
    cm = ConfigManager()
    config = cm.get_all()
    assert "version" in config
    assert "window" in config
    assert "behavior" in config
    assert "tomato" in config
    assert "quick_launch" in config
    assert "appearance" in config
    assert "notification" in config
    print(f"  配置版本: {config['version']}")
    print("✅ 默认配置结构测试通过")


def test_get_set():
    """测试读取和写入配置"""
    cm = ConfigManager()

    # 读取
    opacity = cm.get("window.opacity")
    assert isinstance(opacity, (int, float))
    assert 0 < opacity <= 1.0

    work = cm.get("tomato.work_duration")
    assert isinstance(work, int)
    assert work > 0

    # 不存在的键返回默认值
    val = cm.get("nonexist.key", "fallback")
    assert val == "fallback"

    # 写入
    cm.set("window.opacity", 0.5)
    assert cm.get("window.opacity") == 0.5

    # 恢复
    cm.set("window.opacity", 0.8)
    print("✅ 读取/写入配置测试通过")


def test_get_all_returns_copy():
    """测试 get_all() 返回的是副本，不是引用"""
    cm = ConfigManager()
    config = cm.get_all()
    config["window"]["opacity"] = 999  # 修改副本
    assert cm.get("window.opacity") != 999  # 原值不变
    print("✅ 返回副本测试通过")


def test_nested_set_creates_path():
    """测试嵌套键自动创建中间路径"""
    cm = ConfigManager()
    cm.set("custom.section.value", 42)
    assert cm.get("custom.section.value") == 42
    # 清理
    del cm._config["custom"]
    print("✅ 嵌套键自动创建测试通过")


if __name__ == "__main__":
    test_default_config_structure()
    test_get_set()
    test_get_all_returns_copy()
    test_nested_set_creates_path()
    print("\n所有配置管理测试通过! ✅")
