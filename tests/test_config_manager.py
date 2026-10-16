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
    assert "activity" in config
    assert "plugins" in config
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


def test_user_version_does_not_override_app_version():
    """用户配置里的旧 version 不得覆盖程序版本号（回归测试）

    历史 bug：_merge_config() 里 `result[key] = value` 让用户配置的
    version（如 "1.0.0"）覆盖了 DEFAULT_CONFIG["version"]，save() 再把它
    写回磁盘 —— 于是 user_config.json 的 version 永远停在用户初次安装时的
    值（实测恒为 1.0.0），将来无法识别配置文件的实际 schema。
    """
    from data.config_manager import DEFAULT_CONFIG

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        user_cfg = tmp / "user_config.json"
        user_cfg.write_text(
            json.dumps({"version": "1.0.0", "window": {"opacity": 0.66}}),
            encoding="utf-8",
        )

        # 绕过单例 __init__（它固定指向 ~/.pet_demo），构造一个指向临时目录的实例，
        # 避免污染真实用户配置。
        cm = object.__new__(ConfigManager)
        cm._config_dir = tmp
        cm._user_config_path = user_cfg
        cm._default_config_path = Path(__file__).parent.parent / "config.default.json"
        cm._load_config()

        # 1) 内存中的版本号被钉死为程序版本
        assert cm.get("version") == DEFAULT_CONFIG["version"], cm.get("version")
        assert cm.get("version") != "1.0.0"

        # 2) 用户自己的设置必须原样保留
        assert cm.get("window.opacity") == 0.66

        # 3) 落盘文件里的 version 也必须是程序版本
        on_disk = json.loads(user_cfg.read_text(encoding="utf-8"))
        assert on_disk["version"] == DEFAULT_CONFIG["version"]
        assert on_disk["window"]["opacity"] == 0.66

    print("✅ 配置版本号不被用户值覆盖测试通过")


if __name__ == "__main__":
    test_default_config_structure()
    test_get_set()
    test_get_all_returns_copy()
    test_nested_set_creates_path()
    test_user_version_does_not_override_app_version()
    print("\n所有配置管理测试通过! ✅")
