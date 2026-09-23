"""快捷启动工具模块

功能：
    - 一键启动常用软件
    - 自定义启动命令
    - 支持分类管理
    - 统计使用频率

Events:
    QUICK_LAUNCH: 快捷启动时触发

Usage:
    from tools.quick_launch import QuickLaunch

    launcher = QuickLaunch()
    inv_id = launcher.add_item("Chrome", "start chrome", category="浏览器")
    launcher.launch(inv_id)
"""

import os
import sys
import subprocess
import shlex
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from dataclasses import dataclass, asdict, field

from event_bus import event_bus


@dataclass
class LaunchItem:
    """快捷启动项"""
    id: str
    name: str
    command: str           # 启动命令
    category: str = ""     # 分类
    icon: str = ""         # 图标路径
    run_count: int = 0     # 启动次数
    last_run: str = ""     # 上次启动时间
    description: str = ""  # 描述
    enabled: bool = True   # 是否启用


class QuickLaunch:
    """快捷启动管理器"""

    # 预设常用启动项
    DEFAULT_ITEMS = [
        {"name": "Chrome 浏览器", "command": "start chrome", "category": "浏览器"},
        {"name": "Edge 浏览器", "command": "start msedge", "category": "浏览器"},
        {"name": "记事本", "command": "notepad", "category": "工具"},
        {"name": "计算器", "command": "calc", "category": "工具"},
        {"name": "任务管理器", "command": "taskmgr", "category": "系统"},
        {"name": "VS Code", "command": "code", "category": "开发"},
        {"name": "终端 (CMD)", "command": "cmd", "category": "系统"},
        {"name": "PowerShell", "command": "powershell", "category": "系统"},
        {"name": "画图", "command": "mspaint", "category": "工具"},
        {"name": "文件资源管理器", "command": "explorer", "category": "系统"},
    ]

    def __init__(self, storage_path: str = None):
        self._items: Dict[str, LaunchItem] = {}
        self._storage_path = Path(storage_path) if storage_path else (
            Path.home() / ".pet_demo" / "quick_launch.json"
        )

        # 加载已有项或创建默认项
        self._load_items()

        # 如果没有数据，添加默认项
        if not self._items:
            for item_data in self.DEFAULT_ITEMS:
                self.add_item(
                    name=item_data["name"],
                    command=item_data["command"],
                    category=item_data.get("category", ""),
                )
    def _load_items(self):
        """从文件加载启动项"""
        if self._storage_path.exists():
            try:
                with open(self._storage_path, "r", encoding="utf-8") as f:
                    for item_data in json.load(f):
                        item = LaunchItem(**item_data)
                        if item.enabled:
                            self._items[item.id] = item
            except Exception as e:
                print(f"加载快捷启动项失败: {e}")

    def _save_items(self):
        """保存启动项到文件"""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = [asdict(item) for item in self._items.values()]
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存快捷启动项失败: {e}")

    # ----- 启动项操作 -----

    def add_item(self, name: str, command: str, category: str = "",
                 icon: str = "", description: str = "") -> LaunchItem:
        """
        添加启动项

        Args:
            name: 显示名称
            command: 启动命令
            category: 分类
            icon: 图标路径
            description: 描述

        Returns:
            创建的 LaunchItem
        """
        import uuid

        item = LaunchItem(
            id=str(uuid.uuid4())[:8],
            name=name,
            command=command,
            category=category,
            icon=icon,
            description=description,
        )

        self._items[item.id] = item
        self._save_items()

        return item

    def remove_item(self, item_id: str) -> bool:
        """
        移除启动项

        Args:
            item_id: 启动项ID

        Returns:
            是否成功
        """
        if item_id not in self._items:
            return False

        del self._items[item_id]
        self._save_items()
        return True

    def update_item(self, item_id: str, **kwargs) -> Optional[LaunchItem]:
        """
        更新启动项

        Args:
            item_id: 启动项ID
            **kwargs: 要更新的字段

        Returns:
            更新后的 LaunchItem
        """
        if item_id not in self._items:
            return None

        item = self._items[item_id]
        for key, value in kwargs.items():
            if hasattr(item, key):
                setattr(item, key, value)

        self._save_items()
        return item

    def _parse_command(self, command: str) -> List[str]:
        """
        安全地解析命令字符串为参数列表，避免 shell=True 的命令注入风险

        支持 Windows 的 `start` / `explorer` 等 shell 内置命令：
        - `start chrome` → ['cmd', '/c', 'start', 'chrome']
        - `notepad`      → ['notepad']
        - `code .`       → ['code', '.']

        Args:
            command: 原始命令字符串

        Returns:
            安全的参数列表
        """
        stripped = command.strip()
        lower = stripped.lower()

        # Windows 内置命令需要特殊处理
        if sys.platform == 'win32':
            WINDOWS_BUILTINS = {'start', 'explorer'}
            # 检查是否是 start/explorer 开头的命令
            parts = stripped.split(maxsplit=1)
            if parts and parts[0].lower() in WINDOWS_BUILTINS:
                # start chrome → cmd /c start chrome
                return ['cmd', '/c'] + parts

        # 通用安全解析：使用 shlex 解析为列表
        try:
            args = shlex.split(stripped)
        except ValueError:
            # shlex 解析失败时，使用 split 降级
            args = stripped.split()

        return args

    def launch(self, item_id: str) -> bool:
        """
        执行启动

        Args:
            item_id: 启动项ID

        Returns:
            是否成功启动
        """
        if item_id not in self._items:
            return False

        item = self._items[item_id]

        try:
            # 安全地解析命令（避免 shell=True 的命令注入风险）
            args = self._parse_command(item.command)

            # 在后台启动
            if sys.platform == 'win32':
                # Windows 下使用 creationflags
                subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            else:
                subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            # 更新统计
            item.run_count += 1
            from datetime import datetime
            item.last_run = datetime.now().isoformat()
            self._save_items()

            # 发布事件
            event_bus.publish("QUICK_LAUNCH", {
                "id": item_id,
                "name": item.name,
                "command": item.command,
            })

            return True

        except Exception as e:
            print(f"启动失败 [{item.name}]: {e}")
            return False

    def launch_by_name(self, name: str) -> bool:
        """
        通过名称启动

        Args:
            name: 启动项名称

        Returns:
            是否成功
        """
        for item in self._items.values():
            if item.name == name:
                return self.launch(item.id)
        return False

    # ----- 查询方法 -----

    def get_item(self, item_id: str) -> Optional[LaunchItem]:
        """获取启动项"""
        return self._items.get(item_id)

    def get_all_items(self) -> List[LaunchItem]:
        """获取所有启动项"""
        return list(self._items.values())

    def get_items_by_category(self, category: str) -> List[LaunchItem]:
        """按分类获取"""
        return [i for i in self._items.values() if i.category == category]

    def get_favorites(self, limit: int = 5) -> List[LaunchItem]:
        """获取常用启动项（按使用次数排序）"""
        items = sorted(
            self._items.values(),
            key=lambda x: x.run_count,
            reverse=True
        )
        return items[:limit]

    def search(self, keyword: str) -> List[LaunchItem]:
        """搜索启动项"""
        keyword = keyword.lower()
        return [
            i for i in self._items.values()
            if keyword in i.name.lower() or keyword in i.description.lower()
        ]

    def get_categories(self) -> List[str]:
        """获取所有分类"""
        categories = set()
        for item in self._items.values():
            if item.category:
                categories.add(item.category)
        return sorted(categories)

    def get_statistics(self) -> Dict:
        """获取统计"""
        items = list(self._items.values())
        return {
            "total": len(items),
            "total_launches": sum(i.run_count for i in items),
            "categories": len(self.get_categories()),
            "most_used": items[0].name if items else None,
        }


# 便捷函数
def create_quick_launch() -> QuickLaunch:
    """创建快捷启动管理器"""
    return QuickLaunch()
