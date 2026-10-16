"""插件管理器 - 负责发现、加载和管理插件

目录分层：
    extensions/system/  → 系统内置（自动加载，**卸载 = 停用**，不删程序自带文件）
    extensions/user/    → 用户安装（自动加载，**卸载 = 停用 + 删目录**）
    extensions/dev/     → 开发测试（手动放置）
"""
import os
import shutil
import sys
import types
import importlib.util
import inspect
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from data.config_manager import config_manager
from data.log_manager import log_manager

from .base_plugin import BasePlugin, PluginManifest, MenuAction

# 所有插件挂在这个虚拟父包下，使 plugin.py 内可以使用相对导入
# （如 `from .modes import PRESETS`）。见 T1 改造说明。
_PLUGIN_PKG = "petdemo_plugins"
sys.modules.setdefault(_PLUGIN_PKG, types.ModuleType(_PLUGIN_PKG))


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
    """动态导入插件目录中的 plugin.py，返回 BasePlugin 子类

    T1 改造：以「包」而非「单文件」的方式加载插件。

    原实现用 spec_from_file_location(f"_plugin_{name}", plugin_file) 加载单文件，
    没有包层级，导致 plugin.py 内不能写相对导入，插件只能靠 sys.path 注入 +
    平级绝对导入绕过，模块名（config/logger/utils）会与其他插件互相污染。

    现在改为：
      - 模块全名为 petdemo_plugins.<name>（挂在虚拟父包下）
      - 提供 submodule_search_locations，使相对导入可解析
      - 先注册进 sys.modules 再 exec_module（相对导入依赖此顺序）
    """
    plugin_file = plugin_dir / "plugin.py"
    if not plugin_file.exists():
        return None

    full_name = f"{_PLUGIN_PKG}.{name}"
    spec = importlib.util.spec_from_file_location(
        full_name,
        str(plugin_file),
        submodule_search_locations=[str(plugin_dir)],
    )
    if not spec or not spec.loader:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(full_name, None)
        raise

    for _, cls in inspect.getmembers(module, inspect.isclass):
        if issubclass(cls, BasePlugin) and cls != BasePlugin:
            return cls
    return None


class PluginManager:
    """插件管理器"""

    # 目录分层（按优先级从高到低）
    LAYERS = ["system", "user", "dev"]

    def __init__(self, app=None, base_dir=None):
        self._app = app
        self._plugins: Dict[str, BasePlugin] = {}
        #: 插件根目录。**可注入** —— 测试要在一个临时目录里验证卸载
        #: （卸载会真删目录，绝不能指向仓库里的 `extensions/`）。
        self._base_dir = (Path(base_dir) if base_dir is not None
                          else Path(__file__).parent)
        #: 插件名 → 层 / 目录。卸载要按层区分行为（见 `uninstall`），
        #: 恢复要靠目录把插件找回来（见 `restore`），所以两个都得记。
        self._layer_of: Dict[str, str] = {}
        self._dir_of: Dict[str, Path] = {}

    # ----- 发现与加载 -----

    def discover_and_load(self):
        """扫描所有分层目录，加载插件。

        **跳过已卸载的**（配置 `plugins.disabled`）—— 卸载必须在重启后
        依然生效，否则用户下次开机又看到它回来了。
        """
        disabled = set(self.disabled_names())
        for layer in self.LAYERS:
            layer_dir = self._base_dir / layer
            if not layer_dir.is_dir():
                continue
            for entry in sorted(layer_dir.iterdir()):
                if entry.is_dir():
                    self._load_dir(entry, layer, disabled)

    def _load_layer(self, layer_dir: Path):
        """加载单个分层下的所有插件（层名取目录名）。"""
        disabled = set(self.disabled_names())
        for entry in sorted(layer_dir.iterdir()):
            if entry.is_dir():
                self._load_dir(entry, layer_dir.name, disabled)

    def _load_dir(self, entry: Path, layer: str, disabled: Set[str]) -> bool:
        """加载单个插件目录。返回是否真的加载进来。"""
        skill_path = entry / "SKILL.md"
        if not skill_path.exists():
            return False

        manifest = _parse_skill_md(skill_path)
        name = manifest.name

        if name in disabled:
            # 已卸载。目录信息仍要记下来 —— 用户点「恢复」时靠它把插件找回来。
            self._layer_of[name] = layer
            self._dir_of[name] = entry
            print(f"  [插件] {name}: 已卸载，跳过加载")
            return False

        plugin_class = _import_plugin_class(entry, name)
        if not plugin_class:
            print(f"  [插件] {name}: 未找到 plugin.py")
            return False

        return self._instantiate(manifest, plugin_class, layer, entry)

    def _instantiate(self, manifest: PluginManifest, plugin_class,
                     layer: str = "", plugin_dir: Optional[Path] = None) -> bool:
        """实例化并加载单个插件"""
        name = manifest.name
        if name in self._plugins:
            print(f"  [插件] {name}: 名称冲突，跳过")
            return False

        plugin = plugin_class()
        plugin.manifest = manifest
        plugin.app = self._app

        try:
            if plugin.on_load(self._app):
                self._plugins[name] = plugin
                self._layer_of[name] = layer
                if plugin_dir is not None:
                    self._dir_of[name] = plugin_dir
                print(f"  [插件] {name} v{manifest.version} 已加载")
                return True
            print(f"  [插件] {name}: on_load 返回 False")
        except Exception as e:
            print(f"  [插件] {name}: 加载失败 - {e}")
        return False

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

    # ----- 卸载 / 恢复 -----

    def disabled_names(self) -> List[str]:
        """已卸载（下次启动不再加载）的插件名。"""
        raw = config_manager.get("plugins.disabled", []) or []
        if not isinstance(raw, (list, tuple)):
            return []
        return [str(n) for n in raw if str(n).strip()]

    def layer_of(self, name: str) -> Optional[str]:
        """插件来自哪一层："system" / "user" / "dev" / None（未知）。"""
        return self._layer_of.get(name)

    def is_user_installed(self, name: str) -> bool:
        """用户自己装的（`extensions/user/`）—— 卸载时连目录一起删。"""
        return self._layer_of.get(name) == "user"

    def uninstall(self, name: str) -> Tuple[bool, str]:
        """卸载插件。返回 `(是否成功, 给用户看的一句话)`。

        三件事，缺一不可：
          ① **当前会话立刻停用** —— `on_unload()` + 从 `_plugins` 移除，
             用户马上看不到它的菜单项（不用等重启）；
          ② **记入 `plugins.disabled`** —— 下次启动不再加载；
          ③ **用户层插件连目录一起删** —— 那才叫「卸载」。

        为什么系统层不删目录
            系统插件的目录在程序安装位置里（打包后是
            `_internal/extensions/system/`）：删了会破坏安装完整性，
            而且下次升级 / 重装又回来 —— 「删了个假的东西」比「明确告诉你
            它只是停用」更糟。所以系统层 = 停用，界面文案也如实这么写。
        """
        name = str(name or "").strip()
        if not name:
            return False, "插件名不能为空。"

        layer = self._layer_of.get(name)
        directory = self._dir_of.get(name)

        # ① 当前会话立刻停用
        plugin = self._plugins.pop(name, None)
        if plugin is not None:
            try:
                plugin.on_unload()
            except Exception as e:  # noqa: BLE001 —— 插件自己的清理失败不该挡住卸载
                log_manager.warning(f"插件 [{name}] on_unload 异常: {e}")

        # ② 记入名单 —— 重启后不再加载
        disabled = self.disabled_names()
        if name not in disabled:
            disabled.append(name)
            config_manager.set("plugins.disabled", disabled)
            config_manager.save()

        # ③ 用户层：连目录一起删
        removed_dir = False
        if layer == "user" and directory is not None:
            removed_dir = self._remove_plugin_dir(name, directory)

        log_manager.info(f"插件已卸载: {name} (层={layer or '未知'}, 删目录={removed_dir})")

        if removed_dir:
            return True, f"「{name}」已卸载，插件目录也已删除。"
        if layer == "system":
            return True, (f"「{name}」已停用，下次启动不再加载。\n"
                          "它是系统内置插件，程序自带的文件保持不动 —— "
                          "需要时可在下面点「恢复」。")
        return True, f"「{name}」已停用，下次启动不再加载。"

    def restore(self, name: str) -> Tuple[bool, str]:
        """把已卸载的插件放回加载名单。返回 `(是否成功, 给用户看的一句话)`。

        目录还在就**立刻重新加载**（用户不必重启）；目录已被删掉
        （用户层插件卸载时删了）就只能等重新放进来 —— 这一点如实告诉用户，
        比留一个「恢复了但没反应」的按钮好。
        """
        name = str(name or "").strip()
        disabled = self.disabled_names()
        if name not in disabled:
            return False, f"「{name}」不在已卸载名单里。"

        disabled.remove(name)
        config_manager.set("plugins.disabled", disabled)
        config_manager.save()

        directory = self._dir_of.get(name)
        layer = self._layer_of.get(name) or "user"
        if directory is not None and (Path(directory) / "SKILL.md").exists():
            self._load_dir(Path(directory), layer, set())
            log_manager.info(f"插件已恢复: {name}")
            return True, f"「{name}」已恢复。"

        log_manager.info(f"插件已恢复（目录不存在，需重新安装）: {name}")
        return True, (f"「{name}」已从卸载名单移除，但插件目录已不存在 —— "
                      "要重新放入插件目录才会生效。")

    def _remove_plugin_dir(self, name: str, directory: Path) -> bool:
        """删掉用户插件的目录。**只允许删 `extensions/user/` 下的直接子目录**。

        路径来自加载时记录的真实目录（不是用插件名拼出来的），
        再 `resolve()` 后核对父目录 —— 两道都是为了「绝不误删 user 层之外
        的任何东西」，包括插件名里带 `..` 这种脏数据。
        """
        try:
            target = Path(directory).resolve()
            user_root = (self._base_dir / "user").resolve()
        except OSError:
            return False
        if target.parent != user_root:
            log_manager.warning(f"拒绝删除插件目录（不在 user 层下）: {target}")
            return False
        try:
            shutil.rmtree(target)
            return True
        except OSError as e:  # 权限不足 / 文件被占用 —— 停用仍然有效，别把卸载判失败
            log_manager.warning(f"删除插件目录失败（已停用，下次启动不再加载）: {e}")
            return False

    # ----- 生命周期 -----

    def unload_all(self):
        for name, plugin in list(self._plugins.items()):
            try:
                plugin.on_unload()
            except Exception as e:
                print(f"  [插件] {name}: 卸载异常 - {e}")
        self._plugins.clear()
