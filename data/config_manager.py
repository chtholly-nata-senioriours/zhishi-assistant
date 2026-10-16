"""配置管理模块

负责用户配置的读取、写入、版本控制和自动迁移。

配置文件路径：
    - 默认配置: config.default.json（随版本发布，禁止用户修改）
    - 用户配置: ~/.pet_demo/user_config.json（用户自定义配置）
    - 配置数据存储在 QStandardPaths 的标准配置目录

⚠ 注意：下方 DEFAULT_CONFIG 常量与根目录的 config.default.json 是**两份重复数据**。
    运行时真正生效的是这里的 Python 常量（_load_config 并不读 JSON 文件），
    JSON 文件只用于打包分发与 check_project.py 校验。
    **改配置必须同时改这两处**，否则会出现「改了文件但程序没反应」。
"""

import copy
import json
import os
import shutil
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from data.paths import pet_home

logger = logging.getLogger(__name__)

# 默认配置（必须与根目录 config.default.json 保持一致）
DEFAULT_CONFIG = {
    "version": "1.9.0",
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
    "appearance": {
        # 悬浮球直径（逻辑像素）。2026-10-15 起球是唯一形态
        # （桌宠形态与整套宠物模型资源已移除，`appearance.form` /
        # `pet_name` / `pet_model` / `animation_speed` 一并删除）。
        "orb_size": 52,
        "theme": "default",
    },
    "notification": {
        "enabled": True,
        "rest_reminder_interval": 60,  # 分钟
        "rest_reminder_enabled": True,
    },
    "ai": {
        "enabled": True,
        "hotkey_ask": "alt+q",
        "hotkey_translate": "alt+t",
        "hotkey_capture": "alt+s",
        "provider": "openai_compat",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "vision_model": "",
        "api_key": "",
        "api_key_ref": "",
        "default_preset": "ask",
        "default_language": "zh",
        "response_length": "auto",
        "request_timeout": 60,
        "panel_opacity": 0.95,
        "panel_width": 460,
        "panel_height": 360,
    },
    # 活动建议插件（extensions/system/activity_advisor）
    # 默认**关闭**：enabled 为 False 时插件不订阅事件、不落任何数据
    "activity": {
        "enabled": False,
        "retention_days": 30,      # 本地保留天数，启动时按此清理。
                                   # **必须 ≥ 30**：「趋势」页最长看 30 天，
                                   # 保留更少的话那个视图开箱就是残缺的。
        "min_segment_seconds": 5,  # 短于此时的段丢弃（Alt+Tab 碎片）
        "exclude_apps": [],        # 不想被记录的应用（exe 名，小写）
        "focus_goal_minutes": 240, # 每日深度工作目标（分钟）—— 托盘进度环的分母。
                                   # 刻意偏高（4 小时）：每天都刷满的进度环
                                   # 等于没有信息量。
        # 收工小结：一天最多主动提醒一次，过 nudge_hour 点才考虑。
        # 全屏 / 专注计时中 / 人不在时一律不推（见 engine/activity/reminder.py）。
        "nudge_enabled": True,
        "nudge_hour": 18,
        # 空闲超过这个秒数算「人不在」：这段时间不计入活动时长。
        "away_seconds": 300,
    },
    "plugins": {
        # 已卸载的插件名 —— 启动时跳过加载（控制中心「插件」页可卸载 / 恢复）。
        # 系统内置插件只进这个名单（不删程序自带文件）；
        # 用户插件卸载时连目录一起删，进名单是双保险。
        "disabled": [],
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

    def _setup_paths(self, root: Path = None):
        """设置配置目录和文件路径。

        `root` 只给测试用 —— 生产路径由 `data.paths.pet_home()` 决定
        （默认 `~/.pet_demo`，可用 `PET_DEMO_HOME` 覆盖）。
        """
        self._config_dir = Path(root) if root is not None else pet_home()
        self._user_config_path = self._config_dir / "user_config.json"
        self._default_config_path = Path(__file__).parent.parent / "config.default.json"

        # 确保配置目录存在
        self._config_dir.mkdir(parents=True, exist_ok=True)
        (self._config_dir / "logs").mkdir(exist_ok=True)

    def redirect_for_tests(self, root) -> None:
        """把配置目录改到临时位置并重新加载（**测试专用**）。

        为什么必须有它
            窗口位置、外观形态这类状态是**产品行为**要写盘的。测试只要碰到
            它们（比如构造一个 `ShellWindow` 再拖一下），就会写进用户真实的
            `~/.pet_demo/user_config.json` —— 与 `data/log_manager` 那个
            「测试把日志写进用户目录」是同一类问题。
            原则一样：**测试不许碰用户的运行数据**（见 AGENTS.md §4.9）。
        """
        self._setup_paths(root)
        self._load_config()

    def _load_config(self):
        """加载配置，处理版本迁移。

        只在**磁盘上的内容与内存不一致**时才 `save()`。

        为什么不能无条件 save
            本模块被 import 时就构造单例并调到这里（见文件底部
            `config_manager = ConfigManager()`）。无条件写盘意味着
            「仅仅 import 一下就重写用户的配置文件」—— 备份 / 同步工具会把
            mtime 变化当成真实改动；更要命的是测试没法拦：pytest 的 fixture
            要到测试执行时才跑，那时本模块早 import 完了。
            （实测过：全量测试跑完，用户 `user_config.json` 的 mtime 变了、
            内容字节一模一样。）
        """
        on_disk = None

        if self._user_config_path.exists():
            try:
                with open(self._user_config_path, "r", encoding="utf-8") as f:
                    on_disk = json.load(f)

                # 检查版本兼容性
                user_version = on_disk.get("version", "0.0.0")
                if self._is_version_compatible(user_version, DEFAULT_CONFIG["version"]):
                    self._config = self._merge_config(copy.deepcopy(DEFAULT_CONFIG), on_disk)
                    logger.info(f"加载用户配置成功 (版本: {user_version})")
                else:
                    # 版本不兼容，迁移配置
                    logger.warning(f"配置版本不兼容: {user_version} -> {DEFAULT_CONFIG['version']}")
                    self._config = self._migrate_config(on_disk)
            except Exception as e:
                logger.error(f"读取用户配置失败: {e}，使用默认配置")
                self._config = copy.deepcopy(DEFAULT_CONFIG)
        else:
            # 没有用户配置，使用默认配置
            logger.info("未找到用户配置，使用默认配置")
            self._config = copy.deepcopy(DEFAULT_CONFIG)

        # 配置版本号由代码决定，不允许被用户配置里的旧值覆盖。
        # 否则 _merge_config 会把 user_config["version"] 原样带入并写回磁盘，
        # 使文件里的 version 永远停在用户初次安装时的值（实测恒为 1.0.0），
        # 将来无法识别配置文件的真实 schema —— 同主版本内的小版本迁移会失效。
        self._config["version"] = DEFAULT_CONFIG["version"]

        # 磁盘上没有 / 与内存不一致时才落盘：
        # 前者要「物化」出文件，后者是新增了默认键（新版升级）或发生了迁移。
        if on_disk != self._config:
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
        # deepcopy：`DEFAULT_CONFIG.copy()` 是**浅拷贝**，嵌套节（window /
        # appearance / activity …）会与模块级常量共享同一批 dict 对象。
        # 之后任何一次 `config_manager.set("window.center", ...)` 都会
        # 顺手改掉 DEFAULT_CONFIG —— 那是「重置为默认」和版本迁移的基准，
        # 被污染后默认值就再也不是默认值了。
        new_config = copy.deepcopy(DEFAULT_CONFIG)

        # 迁移可以保留的设置
        if "window" in old_config and "position" in old_config["window"]:
            new_config["window"]["position"] = old_config["window"]["position"]
        if "window" in old_config and "opacity" in old_config["window"]:
            new_config["window"]["opacity"] = old_config["window"]["opacity"]
        if "behavior" in old_config and "sound_enabled" in old_config["behavior"]:
            new_config["behavior"]["sound_enabled"] = old_config["behavior"]["sound_enabled"]
        if "appearance" in old_config and "orb_size" in old_config["appearance"]:
            new_config["appearance"]["orb_size"] = old_config["appearance"]["orb_size"]

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
        return copy.deepcopy(self._config)

    def reset_to_default(self) -> None:
        """重置为默认配置"""
        self._config = copy.deepcopy(DEFAULT_CONFIG)
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



