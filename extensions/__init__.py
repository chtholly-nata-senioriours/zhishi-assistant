"""插件系统

目录分层：
  system/  → 系统内置插件（自动加载）
  user/    → 用户安装插件（自动加载）
  dev/     → 开发测试插件（手动放置）

使用方式：
  from extensions.plugin_manager import PluginManager
  pm = PluginManager(app=petdemo)
  pm.discover_and_load()
"""
from .plugin_manager import PluginManager
from .base_plugin import BasePlugin, PluginManifest, MenuAction

__all__ = ["PluginManager", "BasePlugin", "PluginManifest", "MenuAction"]
