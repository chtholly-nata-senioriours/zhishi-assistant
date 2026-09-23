"""番茄钟工具单元测试"""

import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.timer_tool import TomatoTimer, TimerState
from event_bus import register_event_type

# 确保事件类型已注册
for evt in ("TIMER_START", "TIMER_END", "TIMER_TICK",
            "TIMER_PAUSE", "TIMER_RESUME"):
    register_event_type(evt)


def make_timer(**kwargs):
    """创建番茄钟实例"""
    params = {
        "work_duration": 25,
        "break_duration": 5,
        "long_break_duration": 15,
        "long_break_interval": 4,
    }
    params.update(kwargs)
    return TomatoTimer(**params)


def test_initial_state():
    """测试初始状态"""
    timer = make_timer()
    status = timer.get_status()
    assert status["state"] == "idle"
    assert status["type"] == "work"
    assert status["formatted"] == "00:00"
    assert status["today_count"] == 0
    assert timer.is_running() is False
    assert timer.is_paused() is False
    print(f"  初始状态: {status}")
    print("✅ 初始状态测试通过")


def test_properties():
    """测试属性计算"""
    timer = make_timer(work_duration=1)  # 1分钟
    timer.start("work")
    time.sleep(0.1)
    status = timer.get_status()
    # 开始后剩余约 60秒
    assert 55 <= status["remaining"] <= 60
    assert 0.0 <= status["progress"] <= 0.1
    assert timer.remaining_minutes in (0, 1)
    print(f"  属性: remaining={status['remaining']}s, progress={status['progress']:.2f}")
    timer.stop()
    print("✅ 属性测试通过")


def test_start_stop():
    """测试启动和停止"""
    timer = make_timer(work_duration=1)
    # 启动
    ok = timer.start("work")
    assert ok is True
    assert timer.is_running() is True
    assert timer.state == TimerState.RUNNING
    status = timer.get_status()
    assert status["type"] == "work"

    # 重复启动应失败
    ok = timer.start("work")
    assert ok is False

    # 停止
    timer.stop()
    assert timer.is_running() is False
    assert timer.state == TimerState.IDLE
    print("✅ 启动/停止测试通过")


def test_pause_resume():
    """测试暂停和恢复"""
    timer = make_timer(work_duration=1)
    timer.start("work")
    time.sleep(0.2)

    # 暂停
    ok = timer.pause()
    assert ok is True
    assert timer.is_paused() is True
    assert timer.state == TimerState.PAUSED
    remaining_before = timer.get_status()["remaining"]
    print(f"  暂停时剩余: {remaining_before}s")

    # 暂停后剩余应保持不变
    time.sleep(0.3)
    remaining_after = timer.get_status()["remaining"]
    assert remaining_after == remaining_before  # 暂停后时间不减少

    # 恢复
    ok = timer.resume()
    assert ok is True
    assert timer.is_running() is True
    print("✅ 暂停/恢复测试通过")
    timer.stop()


def test_timer_types():
    """测试不同类型计时"""
    timer = make_timer(work_duration=1, break_duration=1)

    timer.start("work")
    assert timer.timer_type == "work"
    assert timer.get_status()["type"] == "work"
    timer.stop()

    timer.start("break")
    assert timer.timer_type == "break"
    timer.stop()

    timer.start("long_break")
    assert timer.timer_type == "long_break"
    timer.stop()

    # 无效类型
    ok = timer.start("invalid")
    assert ok is False
    print("✅ 计时器类型测试通过")


def test_timer_finishes_after_duration():
    """测试计时器自动完成"""
    timer = make_timer(work_duration=1)  # 1分钟 = 60秒
    # 跳过大部分等待：直接设置剩余很少时间
    timer.start("work")
    timer._remaining_seconds = 1  # 还剩1秒
    # wait for it
    time.sleep(1.5)
    status = timer.get_status()
    assert status["state"] in ("finished", "idle")
    print(f"  计时结束状态: {status['state']}")
    print("✅ 计时自动完成测试通过")


def test_invalid_operations():
    """测试无效操作"""
    timer = make_timer()

    # IDLE 状态下暂停应失败
    assert timer.pause() is False

    # IDLE 状态下恢复应失败
    assert timer.resume() is False

    # 停止空闲计时器应安全
    assert timer.stop() is True
    print("✅ 无效操作测试通过")


if __name__ == "__main__":
    test_initial_state()
    test_properties()
    test_start_stop()
    test_pause_resume()
    test_timer_types()
    test_timer_finishes_after_duration()
    test_invalid_operations()
    print("\n所有番茄钟测试通过! ✅")
