"""插件管理器 - 负责发现、加载和管理插件

目录分层：
    extensions/system/  → 系统内置（自动加载，不可删除）
    extensions/user/    → 用户安装（自动加载）
    extensions/dev/     → 开发测试（手动放置）
"""
import os
import sys
import importlib.util
import inspect
from pathlib import Path
from typing import Dict, List, Optional

from .base_plugin import BasePlugin, PluginManifest, MenuAction


def _parse_skill_md(path: Path) -> PluginManifest:
    """解析 SKILL.md 文件，提取 front matter"""
    content = path.read_text(encoding="utf-8")
    meta = {"name": path.parent.name, "description": "", "version": "1.0.0", "author": "unknown"}
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 2:
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    meta[key.strip()] = val.strip()
    return PluginManifest(
        name=meta["name"],
        description=meta["description"],
        version=meta["version"],
        author=meta["author"],
    )


def _import_plugin_class(plugin_dir: Path, name: str):
    """动态导入插件目录中的 plugin.py，返回 BasePlugin 子类"""
    plugin_file = plugin_dir / "plugin.py"
    if not plugin_file.exists():
        return None

    spec = importlib.util.spec_from_file_location(f"_plugin_{name}", str(plugin_file))
    if not spec or not spec.loader:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for _, cls in inspect.getmembers(module, inspect.isclass):
        if issubclass(cls, BasePlugin) and cls != BasePlugin:
            return cls
    return None


class PluginManager:
    """插件管理器"""

    # 目录分层（按优先级从高到低）
    LAYERS = ["system", "user", "dev"]

    def __init__(self, app=None):
        self._app = app
        self._plugins: Dict[str, BasePlugin] = {}
        self._base_dir = Path(__file__).parent

    # ----- 发现与加载 -----

    def discover_and_load(self):
        """扫描所有分层目录，加载插件"""
        for layer in self.LAYERS:
            layer_dir = self._base_dir / layer
            if not layer_dir.is_dir():
                continue
            self._load_layer(layer_dir)

    def _load_layer(self, layer_dir: Path):
        """加载单个分层下的所有插件"""
        for entry in sorted(layer_dir.iterdir()):
            if not entry.is_dir():
                continue
            skill_path = entry / "SKILL.md"
            if not skill_path.exists():
                continue

            manifest = _parse_skill_md(skill_path)
            plugin_class = _import_plugin_class(entry, manifest.name)
            if not plugin_class:
                print(f"  [插件] {manifest.name}: 未找到 plugin.py")
                continue

            self._instantiate(manifest, plugin_class)

    def _instantiate(self, manifest: PluginManifest, plugin_class):
        """实例化并加载单个插件"""
        name = manifest.name
        if name in self._plugins:
            print(f"  [插件] {name}: 名称冲突，跳过")
            return

        plugin = plugin_class()
        plugin.manifest = manifest
        plugin.app = self._app

        try:
            if plugin.on_load(self._app):
                self._plugins[name] = plugin
                print(f"  [插件] {name} v{manifest.version} 已加载")
            else:
                print(f"  [插件] {name}: on_load 返回 False")
        except Exception as e:
            print(f"  [插件] {name}: 加载失败 - {e}")

    # ----- 查询接口 -----

    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        return self._plugins.get(name)

    def get_all_plugins(self) -> Dict[str, BasePlugin]:
        return dict(self._plugins)

    def get_menu_actions(self) -> List[MenuAction]:
        """收集所有插件的菜单项（按分类排序）"""
        actions = []
        for name, plugin in sorted(self._plugins.items()):
            actions.extend(plugin.get_menu_actions())
        return actions

    # ----- 生命周期 -----

    def unload_all(self):
        for name, plugin in list(self._plugins.items()):
            try:
                plugin.on_unload()
            except Exception as e:
                print(f"  [插件] {name}: 卸载异常 - {e}")
        self._plugins.clear()
