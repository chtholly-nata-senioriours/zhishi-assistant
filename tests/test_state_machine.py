"""状态机单元测试"""

import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.state_machine import PetState, StateMachine
from event_bus import EventBus


def make_isolated_sm():
    """创建使用独立事件总线的状态机（测试隔离）"""
    bus = EventBus()
    sm = StateMachine(event_bus=bus)
    sm.focus_debounce = 0
    sm.state_cooldown = 0
    sm.idle_threshold = 1       # 1秒进入放松
    sm.sleep_threshold = 2      # 2秒进入休眠
    return sm, bus


def test_initial_state():
    """测试初始状态"""
    sm, _ = make_isolated_sm()
    assert sm.current_state == PetState.IDLE
    assert sm.state_name == "idle"
    assert sm.previous_state is None
    print(f"  初始状态: {sm.state_name}")
    print("✅ 初始状态测试通过")


def test_state_transitions():
    """测试基本状态切换"""
    sm, _ = make_isolated_sm()

    # 初始状态
    assert sm.current_state == PetState.IDLE
    print(f"  初始状态: {sm.state_name}")

    # 切换到专注
    ok = sm.transition_to(PetState.FOCUS)
    assert ok is True
    assert sm.current_state == PetState.FOCUS
    assert sm.previous_state == PetState.IDLE
    print(f"  切换到: {sm.state_name}")

    # 切换到放松
    ok = sm.transition_to(PetState.RELAX)
    assert ok is True
    assert sm.current_state == PetState.RELAX
    print(f"  切换到: {sm.state_name}")

    # 相同状态不切换
    ok = sm.transition_to(PetState.RELAX)
    assert ok is False  # 相同状态返回 False
    assert sm.current_state == PetState.RELAX

    print("✅ 状态切换测试通过")


def test_interact_state():
    """测试互动状态"""
    sm, _ = make_isolated_sm()

    # 从空闲进入互动
    sm.transition_to(PetState.FOCUS)
    sm.transition_to(PetState.INTERACT)
    assert sm.current_state == PetState.INTERACT
    assert sm.previous_state == PetState.FOCUS
    print(f"  互动状态: {sm.state_name}")

    print("✅ 互动状态测试通过")


def test_state_info():
    """测试状态信息获取"""
    sm, _ = make_isolated_sm()
    info = sm.get_state_info()

    assert info["current"] == "idle"
    assert info["previous"] is None
    assert isinstance(info["idle_time"], float)
    assert info["idle_time"] >= 0
    assert isinstance(info["since_change"], float)
    print(f"  状态信息: {info}")
    print("✅ 状态信息测试通过")


def test_update_idle_to_relax():
    """测试 update() 从 IDLE 自动切换到 RELAX"""
    sm, _ = make_isolated_sm()
    assert sm.current_state == PetState.IDLE

    # 模拟闲置时间在 idle_threshold 和 sleep_threshold 之间
    sm._last_activity_time = time.time() - 2
    sm.idle_threshold = 1
    sm.sleep_threshold = 10   # 设大 sleep 阈值，确保只触发 relax

    sm.update()
    assert sm.current_state == PetState.RELAX
    print("✅ IDLE → RELAX 自动切换测试通过")


def test_update_relax_to_sleep():
    """测试 update() 从 RELAX 自动切换到 SLEEP"""
    sm, _ = make_isolated_sm()
    sm.transition_to(PetState.RELAX)

    # 模拟闲置超过 sleep_threshold
    sm._last_activity_time = time.time() - 10
    sm.sleep_threshold = 5
    sm.idle_threshold = 1

    sm.update()
    assert sm.current_state == PetState.SLEEP
    print("✅ RELAX → SLEEP 自动切换测试通过")


def test_activity_resets_idle():
    """测试活动检测重置闲置计时"""
    sm, _ = make_isolated_sm()
    sm._last_activity_time = time.time() - 100  # 假装闲置很久

    # 触发活动
    sm._on_activity({"type": "MOUSE_MOVE"})
    idle_time = time.time() - sm._last_activity_time

    assert idle_time < 1  # 闲置时间被重置到 1 秒内
    print("✅ 活动重置闲置计时测试通过")


def test_focus_debounce_blocks_exit():
    """测试专注状态下防抖阻止退出"""
    sm, _ = make_isolated_sm()
    sm.focus_debounce = 10  # 10秒防抖
    sm.state_cooldown = 0

    sm.transition_to(PetState.FOCUS)
    # 立即尝试切换到 RELAX（仍在防抖期内）
    ok = sm.transition_to(PetState.RELAX)
    assert ok is False  # 被防抖拦截
    assert sm.current_state == PetState.FOCUS
    print("✅ 专注防抖测试通过")


def test_force_transition_bypasses_debounce():
    """测试 force=True 绕过防抖"""
    sm, _ = make_isolated_sm()
    sm.focus_debounce = 10
    sm.transition_to(PetState.FOCUS)

    ok = sm.transition_to(PetState.RELAX, force=True)
    assert ok is True
    assert sm.current_state == PetState.RELAX
    print("✅ 强制切换测试通过")


def test_pet_clicked_enters_interact():
    """测试点击桌宠进入互动"""
    sm, bus = make_isolated_sm()
    sm.transition_to(PetState.FOCUS)

    # 模拟点击桌宠事件
    bus.publish("PET_CLICKED", {"x": 100, "y": 100})
    # 互动是异步（Timer 5s后恢复），但切换是同步的
    assert sm.current_state == PetState.INTERACT
    print("✅ 点击桌宠进入互动测试通过")


if __name__ == "__main__":
    test_initial_state()
    test_state_transitions()
    test_interact_state()
    test_state_info()
    test_update_idle_to_relax()
    test_update_relax_to_sleep()
    test_activity_resets_idle()
    test_focus_debounce_blocks_exit()
    test_force_transition_bypasses_debounce()
    test_pet_clicked_enters_interact()
    print("\n所有状态机测试通过! ✅")
