"""日志管理模块

统一管理三种日志：
- 运行日志: ~/.pet_demo/logs/app.log - 记录状态切换、工具触发等
- 用户行为日志: ~/.pet_demo/logs/behavior.log - 匿名记录使用频率
- 配置迁移日志: ~/.pet_demo/logs/config_migration.log

Usage:
    from data.log_manager import log_manager, log_behavior

    # 记录运行日志
    log_manager.info("番茄钟启动")
    log_manager.debug(f"当前状态: {state}")

    # 记录用户行为（需用户同意）
    log_behavior("tomato_started", {"duration": 25})
"""

import os
import json
import logging
import logging.handlers
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime

from data.paths import pet_path


class LogManager:
    """日志管理器 - 统一管理三种日志"""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, log_dir: Path = None):
        if self._initialized:
            return
        self._initialized = True

        self._log_dir = log_dir or pet_path("logs")
        self._log_dir.mkdir(parents=True, exist_ok=True)

        # 用户是否同意记录行为数据
        self._behavior_logging_enabled = self._check_behavior_consent()

        # 初始化三种日志记录器
        self._app_logger = self._setup_logger("app", "app.log")
        self._behavior_logger = self._setup_logger("behavior", "behavior.log")
        self._migration_logger = self._setup_logger("migration", "config_migration.log")

    def _check_behavior_consent(self) -> bool:
        """检查用户是否同意行为记录"""
        consent_file = self._log_dir.parent / "behavior_consent.json"
        if consent_file.exists():
            try:
                with open(consent_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("consent", False)
            except Exception:
                pass
        # 默认不同意
        return False

    def set_behavior_consent(self, consent: bool) -> None:
        """设置用户是否同意行为记录"""
        self._behavior_logging_enabled = consent
        consent_file = self._log_dir.parent / "behavior_consent.json"
        try:
            with open(consent_file, "w", encoding="utf-8") as f:
                json.dump({"consent": consent, "updated_at": datetime.now().isoformat()}, f)
        except Exception as e:
            self._app_logger.error(f"保存行为记录同意状态失败: {e}")

    def _setup_logger(self, name: str, log_file: str) -> logging.Logger:
        """设置日志记录器"""
        logger = logging.getLogger(f"pet_demo.{name}")
        logger.setLevel(logging.DEBUG)

        # 避免重复添加 handler
        if logger.handlers:
            return logger

        # 文件 handler - 按大小轮转 (5MB, 保留3个备份)
        file_handler = logging.handlers.RotatingFileHandler(
            self._log_dir / log_file,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=3,
            encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)

        # 格式化
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(formatter)

        # 控制台 handler (只显示 INFO 及以上)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger

    # --- 便捷方法 ---

    def debug(self, message: str) -> None:
        """记录调试日志"""
        self._app_logger.debug(message)

    def info(self, message: str) -> None:
        """记录信息日志"""
        self._app_logger.info(message)

    def warning(self, message: str) -> None:
        """记录警告日志"""
        self._app_logger.warning(message)

    def error(self, message: str) -> None:
        """记录错误日志"""
        self._app_logger.error(message)

    def exception(self, message: str) -> None:
        """记录异常日志（带堆栈）"""
        self._app_logger.exception(message)

    def log_behavior(self, action: str, data: Dict[str, Any] = None) -> None:
        """
        记录用户行为（需用户同意）

        Args:
            action: 行为类型，如 "tomato_started", "note_created"
            data: 附加数据
        """
        if not self._behavior_logging_enabled:
            return

        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "data": data or {}
        }
        self._behavior_logger.info(json.dumps(entry, ensure_ascii=False))

    def log_migration(self, old_version: str, new_version: str,
                     details: str = "") -> None:
        """记录配置迁移日志"""
        self._migration_logger.info(
            f"迁移: {old_version} -> {new_version} | {details}"
        )

    def get_recent_logs(self, log_type: str = "app", lines: int = 50) -> list:
        """
        获取最近的日志行

        Args:
            log_type: 日志类型 (app/behavior/migration)
            lines: 返回的行数

        Returns:
            日志行列表
        """
        log_file = self._log_dir / f"{log_type}.log"
        if not log_file.exists():
            return []

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
                return all_lines[-lines:] if len(all_lines) > lines else all_lines
        except Exception:
            return []

    def clear_logs(self, log_type: str = None) -> None:
        """
        清空日志文件

        Args:
            log_type: 指定类型，None表示全部
        """
        types = [log_type] if log_type else ["app", "behavior", "migration"]
        for t in types:
            log_file = self._log_dir / f"{t}.log"
            if log_file.exists():
                try:
                    open(log_file, "w").close()
                except Exception:
                    pass


# 全局日志管理器实例
log_manager = LogManager()


# 便捷函数
def log_behavior(action: str, data: Dict[str, Any] = None) -> None:
    """便捷函数：记录用户行为"""
    log_manager.log_behavior(action, data)
