"""规则引擎模块

根据当前状态和概率触发具体动作（动画、音效等）。
规则引擎订阅状态机事件，当状态变化时做出相应反应。

规则格式:
    {
        "when": "STATE_ENTER",
        "state": "focus",
        "then": "play_animation",
        "target": "thumbs_up",
        "chance": 0.8,  # 80% 概率触发
    }

Events (输出到表现层):
    直接调用表现层接口或通过事件总线发送
"""

import random
import time
import logging
from typing import Dict, List, Callable, Optional
from event_bus import event_bus as _global_event_bus

logger = logging.getLogger(__name__)


class Rule:
    """单个规则"""

    def __init__(self,
                 trigger: str,       # 触发事件类型
                 condition: Dict,    # 条件判断
                 action: str,        # 动作类型
                 target: str,        # 动作目标
                 chance: float = 1.0,  # 触发概率 (0-1)
                 cooldown: float = 0,  # 冷却时间（秒）
                 ):
        self.trigger = trigger
        self.condition = condition
        self.action = action
        self.target = target
        self.chance = chance
        self.cooldown = cooldown
        self._last_triggered = 0

    def check_condition(self, event: Dict) -> bool:
        """检查事件是否满足规则条件"""
        # 事件总线会把数据包装在 event["data"] 中
        event_data = event.get("data", event)
        for key, expected in self.condition.items():
            if event_data.get(key) != expected:
                return False
        return True

    def is_on_cooldown(self) -> bool:
        """检查是否在冷却期"""
        if self.cooldown <= 0:
            return False
        return time.time() - self._last_triggered < self.cooldown

    def can_trigger(self) -> bool:
        """检查是否可以触发（概率 + 冷却）"""
        if self.is_on_cooldown():
            return False
        if random.random() > self.chance:
            return False
        return True

    def mark_triggered(self):
        """标记规则已触发"""
        self._last_triggered = time.time()


class RuleEngine:
    """规则引擎 - 根据状态变化触发动作"""

    @staticmethod
    def _build_default_rules() -> List[Rule]:
        """构建默认规则（每次调用生成新实例，避免冷却状态被所有引擎共享）"""
        return [
            # --- 进入专注状态 ---
            Rule(
                trigger="STATE_ENTER",
                condition={"to": "focus"},
                action="play_animation",
                target="thumbs_up",
                chance=0.9,
                cooldown=300,  # 5分钟冷却
            ),
            Rule(
                trigger="STATE_ENTER",
                condition={"to": "focus"},
                action="play_sound",
                target="encourage",
                chance=0.5,
                cooldown=300,
            ),

            # --- 进入放松状态 ---
            # 动画由 AnimController 的 STATE_ANIM_MAP 管理，规则引擎不再触发

            # --- 进入休眠状态 ---
            # 动画由 AnimController 的 STATE_ANIM_MAP 管理，规则引擎不再触发

            # --- 进入互动状态 ---
            Rule(
                trigger="STATE_ENTER",
                condition={"to": "interact"},
                action="play_animation",
                target="wave",
                chance=1.0,
            ),
            Rule(
                trigger="STATE_ENTER",
                condition={"to": "interact"},
                action="play_sound",
                target="greeting",
                chance=0.7,
            ),

            # --- 进入空闲状态（恢复待机） ---
            Rule(
                trigger="STATE_ENTER",
                condition={"to": "idle"},
                action="play_animation",
                target="idle",
                chance=1.0,
            ),

            # --- 退出专注状态 ---
            Rule(
                trigger="STATE_EXIT",
                condition={"from": "focus"},
                action="play_animation",
                target="think",
                chance=0.5,
            ),
        ]

    def __init__(self, event_bus=None):
        self._event_bus = event_bus or _global_event_bus
        self.rules: List[Rule] = []
        self._registered_handlers = {}
        self._setup_default_rules()
        self._setup_listeners()

    def _setup_default_rules(self):
        """设置默认规则"""
        for rule in self._build_default_rules():
            self.add_rule(rule)

    def _setup_listeners(self):
        """设置事件监听器"""
        # 监听状态相关事件
        self._event_bus.subscribe("STATE_ENTER", self._on_state_event)
        self._event_bus.subscribe("STATE_EXIT", self._on_state_event)
        self._event_bus.subscribe("STATE_CHANGE", self._on_state_event)

    def add_rule(self, rule: Rule):
        """添加规则"""
        self.rules.append(rule)

    def remove_rule(self, rule: Rule):
        """移除规则"""
        if rule in self.rules:
            self.rules.remove(rule)

    def _on_state_event(self, event):
        """处理状态事件"""
        event_type = event.get("type")

        for rule in self.rules:
            if rule.trigger != event_type:
                continue

            if not rule.check_condition(event):
                continue

            if not rule.can_trigger():
                continue

            # 触发动作
            rule.mark_triggered()
            self._execute_action(rule.action, rule.target, event)

    def _execute_action(self, action: str, target: str, event: Dict):
        """
        执行动作

        Args:
            action: 动作类型
            target: 动作目标
            event: 触发事件
        """
        logger.debug(f"执行动作: {action} -> {target}")

        if action == "play_animation":
            # 发布动画事件通知表现层
            self._event_bus.publish("REQUEST_ANIMATION", {
                "type": target,
                "triggered_by": event,
            })

        elif action == "play_sound":
            # 发布音效事件
            self._event_bus.publish("REQUEST_SOUND", {
                "type": target,
                "triggered_by": event,
            })

        else:
            logger.warning(f"未知的动作类型: {action}")

    def get_active_rules(self) -> List[Rule]:
        """获取所有活跃的规则"""
        return [r for r in self.rules if not r.is_on_cooldown()]

    def get_rules_summary(self) -> List[Dict]:
        """获取规则概览"""
        return [
            {
                "trigger": r.trigger,
                "condition": r.condition,
                "action": r.action,
                "target": r.target,
                "chance": r.chance,
                "on_cooldown": r.is_on_cooldown(),
            }
            for r in self.rules
        ]


# 便捷函数
def create_rule_engine(event_bus=None) -> RuleEngine:
    """创建规则引擎实例"""
    return RuleEngine(event_bus)
