"""插件系统核心定义

BasePlugin 是所有插件的基类，PluginManifest 描述插件元数据。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Tuple
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

    # ----- v2 功能优先改造新增（全部有默认实现，向后兼容）-----

    def on_ui_ready(self, app) -> None:
        """UI 就绪后调用 —— 此时 app.ui_manager.window 已可用。

        on_load 阶段 UI 尚未创建（main.py 中插件加载早于 _start_ui），
        因此任何依赖主窗口的初始化都应放在这里。

        对 AI 插件尤其重要：面板必须在此阶段**预热**（构建控件树后隐藏待命），
        否则首次唤起要付 ~60ms 的冷构建成本，直接吃掉延迟预算。
        """
        pass

    def register_hotkeys(self) -> List[Tuple[str, Callable[[], None]]]:
        """返回 [(组合键, 回调)]，由宿主统一注册到全局热键服务。

        组合键格式："alt+q" / "ctrl+alt+f9"。
        注册失败（被其他软件占用）只记日志，不阻断加载。
        """
        return []
