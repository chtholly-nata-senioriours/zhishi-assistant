"""状态机模块 (FSM - Finite State Machine)

管理桌宠的状态切换，包括：
- 专注 (FOCUS): 用户高频打字且在工作类应用
- 放松 (RELAX): 无操作 30秒~5分钟
- 休眠 (SLEEP): 无操作 > 5分钟
- 互动 (INTERACT): 用户主动点击桌宠

状态切换规则：
    专注 ←→ 放松 ←→ 休眠
      ↑
    互动 (临时状态，结束后返回之前状态)

防抖策略：
    - 退出专注需 15秒 连续无操作
    - 进入专注后 5分钟内 不再重复触发"鼓励"音效
    - 同一次点击只响应一次

Events:
    STATE_CHANGE: 状态改变时触发
    STATE_ENTER: 进入某状态时触发
    STATE_EXIT: 离开某状态时触发
"""

import time
import threading
from enum import Enum, auto
from typing import Optional, Callable, Dict, Any
from event_bus import event_bus as _global_event_bus


class PetState(Enum):
    """桌宠状态枚举"""
    FOCUS = "focus"           # 专注
    RELAX = "relax"           # 放松
    SLEEP = "sleep"           # 休眠
    INTERACT = "interact"     # 互动
    IDLE = "idle"             # 空闲（初始状态）


class StateMachine:
    """桌宠状态机"""

    def __init__(self, event_bus=None):
        self._event_bus = event_bus or _global_event_bus
        self.current_state = PetState.IDLE
        self.previous_state = None

        # 防抖配置
        self.focus_debounce = 15           # 退出专注的防抖时间（秒）
        self.focus_encourage_cooldown = 300  # 专注鼓励音效冷却（秒）
        self.state_cooldown = 1.0            # 状态切换冷却（秒）

        # 计时器
        self._last_activity_time = time.time()
        self._last_state_change = 0
        self._last_encourage_time = 0
        self._state_lock = threading.Lock()

        # 互动状态之前的状态（用于恢复）
        self._pre_interact_state = None

        # 互动恢复定时器（可取消，防止重复堆叠）
        self._interact_timer = None

        # 无操作阈值（秒）
        self.idle_threshold = 30     # 进入放松
        self.sleep_threshold = 300     # 进入休眠

        # 注册事件监听
        self._setup_event_listeners()

    def _setup_event_listeners(self):
        """设置事件监听器"""
        self._event_bus.subscribe("KEYBOARD_HIGH_RATE", self._on_keyboard_high)
        self._event_bus.subscribe("MOUSE_CLICK", self._on_mouse_click)
        self._event_bus.subscribe("MOUSE_MOVE", self._on_activity)
        self._event_bus.subscribe("PET_CLICKED", self._on_pet_clicked)

    # ----- 状态属性 -----

    @property
    def state_name(self) -> str:
        """当前状态名称"""
        return self.current_state.value

    # ----- 事件处理 -----

    def _on_keyboard_high(self, event):
        """键盘高频事件 - 可能进入专注状态"""
        self._activity_detected()

        # 只有不在互动状态时才切换
        if self.current_state != PetState.INTERACT:
            # 检查是否在专注状态
            if self.current_state == PetState.FOCUS:
                return

            # 检查是否在冷却期
            if time.time() - self._last_state_change < self.state_cooldown:
                return

            self.transition_to(PetState.FOCUS)

    def _on_mouse_click(self, event):
        """鼠标点击事件"""
        self._activity_detected()

    def _on_activity(self, event):
        """通用活动检测"""
        self._activity_detected()

    def _on_pet_clicked(self, event):
        """桌宠被点击 - 切换到互动状态"""
        if self.current_state != PetState.INTERACT:
            self._pre_interact_state = self.current_state
            self.transition_to(PetState.INTERACT)

            # 交互状态 5秒后自动恢复（先取消旧定时器，防止快速连点堆叠）
            if self._interact_timer:
                self._interact_timer.cancel()
            self._interact_timer = threading.Timer(5.0, self._restore_after_interact)
            self._interact_timer.daemon = True
            self._interact_timer.start()

    def _restore_after_interact(self):
        """互动状态结束后恢复之前状态"""
        if self.current_state == PetState.INTERACT:
            if self._pre_interact_state:
                self.transition_to(self._pre_interact_state)
            else:
                self.transition_to(PetState.IDLE)

    def _activity_detected(self):
        """记录活动时间"""
        self._last_activity_time = time.time()

        # 从休眠/放松回到空闲
        if self.current_state in (PetState.SLEEP, PetState.RELAX):
            self.transition_to(PetState.IDLE)

    # ----- 核心方法 -----

    def transition_to(self, new_state: PetState, force: bool = False) -> bool:
        """
        切换到指定状态

        Args:
            new_state: 目标状态
            force: 是否强制切换（忽略冷却和防抖）

        Returns:
            是否成功切换
        """
        with self._state_lock:
            # 忽略相同状态
            if self.current_state == new_state:
                return False

            # 检查冷却时间
            if not force and time.time() - self._last_state_change < self.state_cooldown:
                return False

            # 专注状态的防抖检查
            if self.current_state == PetState.FOCUS and new_state != PetState.INTERACT:
                if not force and time.time() - self._last_activity_time < self.focus_debounce:
                    return False

            # 执行状态切换
            old_state = self.current_state
            self.previous_state = old_state
            self.current_state = new_state
            self._last_state_change = time.time()

            print(f"状态切换: {old_state.value} -> {new_state.value}")

        # 发布状态退出事件
        self._event_bus.publish("STATE_EXIT", {
            "from": old_state.value,
            "to": new_state.value,
        })

        # 发布状态改变事件
        self._event_bus.publish("STATE_CHANGE", {
            "from": old_state.value,
            "to": new_state.value,
            "timestamp": time.time(),
        })

        # 发布状态进入事件
        self._event_bus.publish("STATE_ENTER", {
            "from": old_state.value,
            "to": new_state.value,
        })

        return True

    def update(self):
        """
        状态机更新 - 定期检查并自动切换状态
        应在主循环中定期调用
        """
        if self.current_state == PetState.INTERACT:
            # 互动状态不自动切换
            return

        idle_time = time.time() - self._last_activity_time

        if idle_time >= self.sleep_threshold:
            # 进入休眠状态
            if self.current_state != PetState.SLEEP:
                self.transition_to(PetState.SLEEP)

        elif idle_time >= self.idle_threshold:
            # 进入放松状态
            if self.current_state == PetState.IDLE:
                self.transition_to(PetState.RELAX)
            elif self.current_state == PetState.FOCUS:
                # 从专注切换到放松需要更长的防抖
                pass  # 由 _on_keyboard_high 的控制逻辑处理

    def check_focus_eligible(self) -> bool:
        """检查是否可以触发专注状态的鼓励"""
        if self.current_state != PetState.FOCUS:
            return False
        if time.time() - self._last_encourage_time < self.focus_encourage_cooldown:
            return False
        self._last_encourage_time = time.time()
        return True

    def get_state_info(self) -> Dict:
        """获取当前状态信息"""
        return {
            "current": self.current_state.value,
            "previous": self.previous_state.value if self.previous_state else None,
            "idle_time": time.time() - self._last_activity_time,
            "since_change": time.time() - self._last_state_change,
        }

# 便捷函数
def create_state_machine(event_bus=None) -> StateMachine:
    """创建状态机实例"""
    return StateMachine(event_bus)
