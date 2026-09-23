"""配置管理模块

负责用户配置的读取、写入、版本控制和自动迁移。

配置文件路径：
    - 默认配置: config.default.json（随版本发布，禁止用户修改）
    - 用户配置: ~/.pet_demo/user_config.json（用户自定义配置）
    - 配置数据存储在 QStandardPaths 的标准配置目录
"""

import json
import os
import shutil
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_CONFIG = {
    "version": "1.0.0",
    "window": {
        "position": [100, 200],
        "size": [200, 200],
        "opacity": 0.8,
        "always_on_top": True,
        "show_on_startup": True,
    },
    "behavior": {
        "idle_threshold": 30,      # 秒，进入放松状态
        "sleep_threshold": 300,      # 秒，进入休眠状态
        "focus_threshold": 60,       # 次/30秒，进入专注状态
        "focus_debounce": 15,       # 秒，退出专注状态的防抖时间
        "state_switch_cooldown": 1, # 秒，状态切换冷却时间
        "sound_enabled": True,
        "volume": 0.5,
    },
    "tomato": {
        "work_duration": 25,       # 分钟
        "break_duration": 5,       # 分钟
        "long_break_duration": 15, # 分钟
        "long_break_interval": 4,  # 个番茄钟后长休息
        "auto_start_break": False,
    },
    "quick_launch": {
        "items": [
            {"name": "浏览器", "command": "start chrome"},
            {"name": "记事本", "command": "notepad"},
            {"name": "计算器", "command": "calc"},
        ]
    },
    "appearance": {
        "pet_name": "小宠",
        "pet_model": "default",
        "theme": "default",
        "animation_speed": 1.0,
    },
    "notification": {
        "enabled": True,
        "rest_reminder_interval": 60,  # 分钟
        "rest_reminder_enabled": True,
    },
}


class ConfigManager:
    """配置管理器 - 单例模式"""

    _instance = None
    _config_dir: Path = None
    _user_config_path: Path = None
    _config: Dict[str, Any] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._setup_paths()
        self._load_config()

    def _setup_paths(self):
        """设置配置目录和文件路径"""
        # 使用用户目录下的 .pet_demo 文件夹
        self._config_dir = Path.home() / ".pet_demo"
        self._user_config_path = self._config_dir / "user_config.json"
        self._default_config_path = Path(__file__).parent.parent / "config.default.json"

        # 确保配置目录存在
        self._config_dir.mkdir(parents=True, exist_ok=True)
        (self._config_dir / "logs").mkdir(exist_ok=True)

    def _load_config(self):
        """加载配置，处理版本迁移"""
        # 尝试加载用户配置
        if self._user_config_path.exists():
            try:
                with open(self._user_config_path, "r", encoding="utf-8") as f:
                    user_config = json.load(f)

                # 检查版本兼容性
                user_version = user_config.get("version", "0.0.0")
                if self._is_version_compatible(user_version, DEFAULT_CONFIG["version"]):
                    self._config = self._merge_config(DEFAULT_CONFIG.copy(), user_config)
                    logger.info(f"加载用户配置成功 (版本: {user_version})")
                else:
                    # 版本不兼容，迁移配置
                    logger.warning(f"配置版本不兼容: {user_version} -> {DEFAULT_CONFIG['version']}")
                    self._config = self._migrate_config(user_config)
            except Exception as e:
                logger.error(f"读取用户配置失败: {e}，使用默认配置")
                self._config = DEFAULT_CONFIG.copy()
        else:
            # 没有用户配置，使用默认配置
            logger.info("未找到用户配置，使用默认配置")
            self._config = DEFAULT_CONFIG.copy()

        # 保存配置（确保写回磁盘）
        self.save()

    def _is_version_compatible(self, user_version: str, app_version: str) -> bool:
        """检查版本是否兼容（简单比较主版本号）"""
        try:
            user_major = user_version.split(".")[0]
            app_major = app_version.split(".")[0]
            return user_major == app_major
        except Exception:
            return False

    def _merge_config(self, default: Dict, user: Dict) -> Dict:
        """递归合并配置，用户配置优先"""
        result = default.copy()
        for key, value in user.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_config(result[key], value)
            else:
                result[key] = value
        return result

    def _migrate_config(self, old_config: Dict) -> Dict:
        """迁移旧版本配置到新版"""
        logger.info("执行配置迁移...")
        new_config = DEFAULT_CONFIG.copy()

        # 迁移可以保留的设置
        if "window" in old_config and "position" in old_config["window"]:
            new_config["window"]["position"] = old_config["window"]["position"]
        if "window" in old_config and "opacity" in old_config["window"]:
            new_config["window"]["opacity"] = old_config["window"]["opacity"]
        if "behavior" in old_config and "sound_enabled" in old_config["behavior"]:
            new_config["behavior"]["sound_enabled"] = old_config["behavior"]["sound_enabled"]
        if "appearance" in old_config and "pet_name" in old_config["appearance"]:
            new_config["appearance"]["pet_name"] = old_config["appearance"]["pet_name"]

        # 记录迁移日志
        migration_log = self._config_dir / "logs" / "config_migration.log"
        try:
            with open(migration_log, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 迁移: {old_config.get('version', 'unknown')} -> {DEFAULT_CONFIG['version']}\n")
        except Exception:
            pass

        return new_config

    # --- 公共 API ---

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值（支持点号分隔的路径）

        Args:
            key: 配置键，如 "window.opacity" 或 "tomato.work_duration"
            default: 默认值

        Returns:
            配置值
        """
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value: Any) -> None:
        """
        设置配置值

        Args:
            key: 配置键，支持点号路径
            value: 要设置的值
        """
        keys = key.split(".")
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
        logger.debug(f"设置配置: {key} = {value}")

    def save(self) -> bool:
        """保存配置到用户配置文件"""
        try:
            with open(self._user_config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
            logger.info(f"配置已保存到: {self._user_config_path}")
            return True
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return False

    def get_all(self) -> Dict:
        """获取完整配置副本"""
        import copy
        return copy.deepcopy(self._config)

    def reset_to_default(self) -> None:
        """重置为默认配置"""
        self._config = DEFAULT_CONFIG.copy()
        self.save()
        logger.info("配置已重置为默认值")

    @property
    def config_dir(self) -> Path:
        """配置目录路径"""
        return self._config_dir


# 全局配置管理器实例
config_manager = ConfigManager()


# 兼容旧代码的便捷函数
def get_config(key: str = None, default: Any = None) -> Any:
    """便捷函数：获取配置值"""
    if key is None:
        return config_manager.get_all()
    return config_manager.get(key, default)


def set_config(key: str, value: Any) -> None:
    """便捷函数：设置配置值"""
    config_manager.set(key, value)


def save_config() -> bool:
    """便捷函数：保存配置"""
    return config_manager.save()



