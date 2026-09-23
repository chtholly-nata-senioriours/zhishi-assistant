"""插件系统核心定义

BasePlugin 是所有插件的基类，PluginManifest 描述插件元数据。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from PySide6.QtWidgets import QDialog


@dataclass
class PluginManifest:
    """插件清单（解析自 SKILL.md）"""
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    author: str = "system"
    category: str = "tool"      # tool / animation / sensor


@dataclass
class MenuAction:
    """菜单项定义"""
    name: str                   # 菜单显示名称
    callback: Callable          # 点击回调
    category: str = ""          # 分组标识，相同分组的排在一起


class BasePlugin:
    """所有插件必须继承的基类"""

    def __init__(self):
        self.manifest: PluginManifest = PluginManifest()
        self.app = None          # PetDemo 实例引用

    def on_load(self, app) -> bool:
        """插件加载时调用，返回 False 表示加载失败"""
        return True

    def on_unload(self):
        """插件卸载时调用"""
        pass

    def get_menu_actions(self) -> List[MenuAction]:
        """返回要在右键菜单中显示的动作列表"""
        return []

    def get_dialog(self, parent=None) -> Optional[QDialog]:
        """返回插件的主对话框（可选）"""
        return None
