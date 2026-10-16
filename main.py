"""知时助手 - 主入口

一个可爱的桌面宠物，能感知你的工作状态，
    在你专注时安静陪伴，在你休息时活泼互动。

启动方式：
    python main.py

依赖安装：
    pip install -r requirements.txt

功能特性：
    - 感知层：键盘/鼠标监听、窗口检测、定时触发
    - 决策引擎：状态机 + 规则引擎
    - 表现层：半透明UI + 动画 + 气泡提示
    - 工具层：番茄钟、便签、快捷启动
"""

import sys
import os
import time
import signal
import threading
from pathlib import Path


# ============================================================
# Windows UTF-8 控制台编码设置（解决中文乱码）
# ============================================================

if sys.platform == "win32":
    import io
    if sys.stdout and hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr and hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ============================================================
# 依赖检查
# ============================================================

def check_dependencies():
    """检查必要的依赖"""
    missing = []

    try:
        import PySide6
    except ImportError:
        missing.append("PySide6")

    try:
        import pynput
    except ImportError:
        print("警告: pynput 未安装，输入监听功能将不可用")
        print("  运行: pip install pynput")

    try:
        import win32gui  # 仅 Windows
    except ImportError:
        if os.name == "nt":
            print("警告: win32gui 未安装，窗口监听功能将不可用")
            print("  运行: pip install pywin32")

    if missing:
        print("错误: 缺少必要的依赖:")
        for pkg in missing:
            print(f"  - {pkg}")
        print("\n请运行: pip install -r requirements.txt")
        sys.exit(1)


check_dependencies()


# ============================================================
# 模块导入
# ============================================================

from PySide6.QtWidgets import QApplication

from event_bus import event_bus
from data.config_manager import config_manager
from data.log_manager import log_manager

from sensor.input_monitor import InputMonitor
from sensor.window_monitor import WindowMonitor
from sensor.time_trigger import TimeTrigger

from engine.state_machine import PetState, create_state_machine
from engine.rule_engine import create_rule_engine

from presentation.ui_renderer import UIManager
from presentation.anim_controller import AnimController
from presentation.tray_icon import TrayIcon

from extensions.plugin_manager import PluginManager
from native.hotkey import HotkeyService


# ============================================================
# 主程序
# ============================================================

class PetDemo:
    """知时助手主程序"""

    def __init__(self):
        self._running = False
        self._update_timer = None

        # 组件引用
        self.config = config_manager
        self.log = log_manager

        # 感知层
        self.input_monitor = None
        self.window_monitor = None
        self.time_trigger = None

        # 决策层
        self.state_machine = None
        self.rule_engine = None

        # 表现层
        self.ui_manager = UIManager()
        self.anim_controller = None

        # 插件系统（替代旧的工具层）
        self.plugin_manager = None

        # 系统托盘
        self.tray_icon = None

        # 全局热键服务（v2 新增，UI 就绪后创建）
        self.hotkeys = None

        # 工具层（由插件负责初始化）
        self.timer = None
        # 插件挂上来的能力（便签 / 快捷启动已随 P2.20 移除，此处不再预留）

        # 信号处理
        if os.name != "nt":
            signal.signal(signal.SIGINT, self._signal_handler)

        print("知时助手 初始化完成")

    def _signal_handler(self, signum, frame):
        """信号处理"""
        print("\n收到中断信号，正在退出...")
        self.stop()

    def start(self):
        """启动知时助手"""
        if self._running:
            return

        self._running = True
        print("\n正在启动知时助手...")

        # --- 初始化数据层 ---
        print("  -> 初始化配置...")
        self._setup_config()

        # --- 初始化感知层 ---
        print("  -> 启动感知层...")
        self._start_sensors()

        # --- 初始化决策层 ---
        print("  -> 启动决策引擎...")
        self._start_engine()

        # --- 从配置同步状态机阈值（必须在引擎创建之后）---
        if hasattr(self, "state_machine") and self.state_machine:
            self.state_machine.idle_threshold = self.config.get("behavior.idle_threshold", 30)
            self.state_machine.sleep_threshold = self.config.get("behavior.sleep_threshold", 300)
            self.state_machine.focus_debounce = self.config.get("behavior.focus_debounce", 15)
            self.state_machine.state_cooldown = self.config.get("behavior.state_switch_cooldown", 1)

        # --- 输入监听器的专注阈值同步 ---
        if self.input_monitor:
            self.input_monitor._focus_threshold = self.config.get("behavior.focus_threshold", 60)

        # --- 初始化插件系统（替代旧工具层）---
        print("  -> 加载插件...")
        self.plugin_manager = PluginManager(app=self)
        self.plugin_manager.discover_and_load()

        # --- 初始化表现层 ---
        print("  -> 启动UI...")
        self._start_ui()

        # --- 通知插件 UI 已就绪（T3）：面板预热、热键注册都在此发生 ---
        self._notify_ui_ready()

        # --- 启动主循环 ---
        print("\n知时助手已启动！")
        print("   右键点击悬浮球打开菜单")
        print("   拖动悬浮球可移动位置")

        self._setup_state_update()

    def _setup_config(self):
        """配置初始化"""
        # 读取一些配置
        position = self.config.get("window.position")
        opacity = self.config.get("window.opacity")

        print(f"  配置加载完成 (位置: {position}, 透明度: {opacity})")

    def _start_sensors(self):
        """启动感知层"""
        # 输入监听
        self.input_monitor = InputMonitor()
        self.input_monitor.start()

        # 窗口监听
        self.window_monitor = WindowMonitor()
        self.window_monitor.start()

        # 定时触发器
        self.time_trigger = TimeTrigger()
        self.time_trigger.start()

        print("  感知层已启动")

    def _start_engine(self):
        """启动决策引擎"""
        # 状态机
        self.state_machine = create_state_machine()

        # 规则引擎
        self.rule_engine = create_rule_engine()

        # 注册更多事件监听
        event_bus.subscribe("STATE_CHANGE", self._on_state_change)
        event_bus.subscribe("MOUSE_CLICK", self._on_mouse_click)
        event_bus.subscribe("PET_CLICKED", self._on_pet_clicked)

        print("  决策引擎已启动")

    def _on_state_change(self, event):
        """状态变化回调"""
        data = event.get("data", {})
        pet_state = data.get("to", "unknown")
        print(f"  状态: {data.get('from', '?')} -> {pet_state}")

    def _on_mouse_click(self, event):
        """鼠标点击回调"""
        # 记录活跃时间，重置空闲计时
        log_manager.debug("鼠标点击")

    def _on_pet_clicked(self, event):
        """悬浮球被点击"""
        print("  悬浮球被点击了！")

    def _start_ui(self):
        """启动UI"""
        # 注入插件管理器到 UI
        if self.plugin_manager:
            self.ui_manager.set_plugin_manager(self.plugin_manager)
        # 注入自身：控制中心要读状态机 / 插件管理器
        self.ui_manager.set_pet_app(self)

        self.ui_manager.initialize()
        self.ui_manager.show()

        # 动画控制器
        window = self.ui_manager.window
        if window:
            self.anim_controller = AnimController()
            # 球没有精灵图 → `animation_target()` 返回 None，这里不设图片目标。
            # AnimController 仍要做两件事：① 把 `text_requested` 转成气泡；
            # ② 按形态的 `wants_shell_motion()` 决定数值动画要不要 move 外壳
            #    （球为 False，否则拖动后会被动画拽回原坐标）。
            # 落点要不要设由形态决定，将来接入有精灵图的形态时在这里补。
            if window.animation_target() is not None:
                self.anim_controller.set_target(window.animation_target())
            self.ui_manager.set_anim_controller(self.anim_controller)

        # --- 全局热键服务（需 QApplication 已创建）---
        self.hotkeys = HotkeyService()
        self.hotkeys.install(self.ui_manager.app)

        # 显示欢迎信息
        if self.ui_manager.window:
            self.ui_manager.window.show_text("嗨~ 我在这儿！", 3000)

        # --- 系统托盘（UI 就绪后创建）---
        self._start_tray()

    def _notify_ui_ready(self):
        """T3：UI 就绪后通知插件，并统一注册它们声明的全局热键。

        分两步：先 on_ui_ready（插件借此预热面板），再 register_hotkeys
        （回调里通常要引用已预热的面板，故必须在其后）。
        """
        plugins = self.plugin_manager.get_all_plugins() if self.plugin_manager else {}

        for name, plugin in plugins.items():
            try:
                plugin.on_ui_ready(self)
            except Exception as e:
                log_manager.error(f"插件 [{name}] on_ui_ready 失败: {e}")

        for name, plugin in plugins.items():
            try:
                for combo, callback in plugin.register_hotkeys():
                    if self.hotkeys and self.hotkeys.register(combo, callback):
                        log_manager.info(f"热键已注册: {combo} (插件 {name})")
                        print(f"  [热键] {combo} 已注册")
                    else:
                        log_manager.warning(f"热键注册失败（可能被占用）: {combo}")
                        print(f"  [热键] {combo} 注册失败，可从托盘菜单唤起")
            except Exception as e:
                log_manager.error(f"插件 [{name}] 注册热键失败: {e}")

    def _start_tray(self):
        """创建系统托盘图标"""
        try:
            icon_path = str(Path(__file__).parent / "图标.ico")
            self.tray_icon = TrayIcon(app=self, icon_path=icon_path)
            self.tray_icon.quit_requested.connect(self.stop)
            # 让窗口能引用托盘（关闭时气泡提示用）
            if self.ui_manager.window:
                self.ui_manager.window._tray_icon = self.tray_icon
            # 开机自启静默模式：不弹窗口，直接进托盘
            if "--minimized" in sys.argv:
                self.ui_manager.window.hide()
                self.tray_icon.show_message("知时助手", "已在托盘静默启动，双击图标唤出~")
                print("静默启动完成（托盘模式）")
            log_manager.info("系统托盘已启动")
        except Exception as e:
            log_manager.error(f"托盘初始化失败: {e}")
            self.tray_icon = None

    def _setup_state_update(self):
        """设置状态更新定时器"""
        def update_loop():
            while self._running:
                try:
                    # 更新状态机
                    if self.state_machine:
                        self.state_machine.update()

                    # 更新UI动画
                    if self.ui_manager and self.ui_manager.window:
                        pass  # UI在主线程更新

                except Exception as e:
                    log_manager.error(f"更新循环错误: {e}")

                time.sleep(1)  # 每秒更新一次

        self._update_thread = threading.Thread(target=update_loop, daemon=True)
        self._update_thread.start()

    def stop(self):
        """停止知时助手"""
        print("\n正在停止知时助手...")
        self._running = False

        # 停止感知层
        if self.input_monitor:
            self.input_monitor.stop()
        if self.window_monitor:
            self.window_monitor.stop()
        if self.time_trigger:
            self.time_trigger.stop()

        # 注销全局热键
        if self.hotkeys:
            self.hotkeys.unregister_all()

        # 隐藏托盘图标（否则图标残留到鼠标划过）
        if self.tray_icon:
            try:
                self.tray_icon.hide()
            except Exception:
                pass

        log_manager.info("知时助手已停止")
        print("再见！")

        # 关闭进程级共享 Store（会话 / 预设库）。放在退出前 —— 插件只借用
        # 它，不负责关闭，真正释放必须由进程统一做（见 engine.ai.store）。
        try:
            from engine.ai import close_shared_store

            close_shared_store()
        except Exception:  # noqa: BLE001 —— 收尾失败不该阻止退出
            pass

        # 退出 Qt 事件循环（关闭窗口）
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                app.quit()
        except ImportError:
            pass

    def run(self):
        """主循环"""
        try:
            self.start()
            self.ui_manager.run()  # 进入Qt事件循环
        except KeyboardInterrupt:
            self.stop()
        except Exception as e:
            print(f"运行错误: {e}")
            self.stop()


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    pet = PetDemo()
    pet.run()
