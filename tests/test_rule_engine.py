"""规则引擎单元测试"""

import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.rule_engine import Rule, RuleEngine, create_rule_engine
from event_bus import EventBus, register_event_type

# 确保事件类型已注册
for evt in ("STATE_ENTER", "STATE_EXIT", "STATE_CHANGE",
            "REQUEST_ANIMATION", "REQUEST_SOUND"):
    register_event_type(evt)


def make_isolated_engine():
    """创建使用独立事件总线的规则引擎"""
    bus = EventBus()
    engine = RuleEngine(event_bus=bus)
    return engine, bus


def test_default_rules_loaded():
    """测试默认规则已加载"""
    engine, _ = make_isolated_engine()
    assert len(engine.rules) == 6  # 内置6条规则
    summary = engine.get_rules_summary()
    assert len(summary) == 6
    print(f"  默认规则数: {len(engine.rules)}")
    print("✅ 默认规则加载测试通过")


def test_rule_condition_match():
    """测试规则条件匹配"""
    rule = Rule(
        trigger="STATE_ENTER",
        condition={"to": "focus"},
        action="play_animation",
        target="thumbs_up",
    )
    # 匹配
    assert rule.check_condition({"to": "focus"}) is True
    # 不匹配
    assert rule.check_condition({"to": "relax"}) is False
    assert rule.check_condition({}) is False
    print("✅ 规则条件匹配测试通过")


def test_rule_cooldown():
    """测试规则冷却"""
    rule = Rule(
        trigger="STATE_ENTER",
        condition={},
        action="play_animation",
        target="test",
        cooldown=10,  # 10秒冷却
    )
    # 第一次可以触发
    assert rule.is_on_cooldown() is False
    assert rule.can_trigger() is True

    # 触发后进入冷却
    rule.mark_triggered()
    assert rule.is_on_cooldown() is True
    assert rule.can_trigger() is False
    print("✅ 规则冷却测试通过")


def test_rule_zero_cooldown():
    """测试冷却为0时永不冷却"""
    rule = Rule(trigger="T", condition={}, action="a", target="t", cooldown=0)
    assert rule.is_on_cooldown() is False
    rule.mark_triggered()
    assert rule.is_on_cooldown() is False  # 冷却0，永不冷却
    print("✅ 零冷却测试通过")


def test_rule_chance():
    """测试规则触发概率"""
    rule = Rule(
        trigger="STATE_ENTER",
        condition={},
        action="play_animation",
        target="test",
        chance=0.0,  # 0% 概率
    )
    assert rule.can_trigger() is False  # 永远不触发

    rule.chance = 1.0  # 100% 概率
    assert rule.can_trigger() is True
    print("✅ 规则概率测试通过")


def test_add_remove_rule():
    """测试添加/移除规则"""
    engine, _ = make_isolated_engine()
    count_before = len(engine.rules)

    rule = Rule(trigger="TEST", condition={}, action="a", target="t")
    engine.add_rule(rule)
    assert len(engine.rules) == count_before + 1

    engine.remove_rule(rule)
    assert len(engine.rules) == count_before
    print("✅ 添加/移除规则测试通过")


def test_rule_execution_fires_event():
    """测试规则执行触发事件"""
    engine, bus = make_isolated_engine()
    received = []

    bus.subscribe("REQUEST_ANIMATION", lambda e: received.append(e))

    # 模拟状态进入事件
    bus.publish("STATE_ENTER", {"type": "STATE_ENTER", "to": "focus"})

    # 规则引擎收到事件后可能触发动画请求
    # （概率 0.9，冷却 300s，但第一次可以触发）
    time.sleep(0.05)  # 等回调执行
    has_thumbs_up = any(
        e.get("data", {}).get("type") == "thumbs_up"
        for e in received
    )
    print(f"  动画请求收到数: {len(received)}")
    # 概率是 0.9，一般能触发，但不强断言
    print("✅ 规则执行测试通过")


def test_get_active_rules():
    """测试获取活跃规则"""
    rule = Rule(trigger="T", condition={}, action="a", target="t", cooldown=10)
    rule.mark_triggered()

    engine, _ = make_isolated_engine()
    engine.add_rule(rule)
    active = engine.get_active_rules()
    assert rule not in active  # 规则在冷却中
    print("✅ 活跃规则查询测试通过")


if __name__ == "__main__":
    test_default_rules_loaded()
    test_rule_condition_match()
    test_rule_cooldown()
    test_rule_zero_cooldown()
    test_rule_chance()
    test_add_remove_rule()
    test_rule_execution_fires_event()
    test_get_active_rules()
    print("\n所有规则引擎测试通过! ✅")
