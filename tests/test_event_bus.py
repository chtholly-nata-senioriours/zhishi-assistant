"""事件总线单元测试"""

import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from event_bus import EventBus, register_event_type

# 注册测试专用事件类型（消除 WARNING）
register_event_type("TEST_EVENT")
register_event_type("TEST_STATS")


def test_event_bus_basic():
    """测试事件总线基本功能"""
    bus = EventBus()
    received = []

    def handler(event):
        received.append(event)

    # 订阅和发布
    bus.subscribe("MOUSE_CLICK", handler)
    bus.publish("MOUSE_CLICK", {"x": 100, "y": 200})

    assert len(received) == 1
    assert received[0]["type"] == "MOUSE_CLICK"
    assert received[0]["data"]["x"] == 100
    print("✅ 事件订阅/发布测试通过")


def test_unsubscribe():
    """测试取消订阅"""
    bus = EventBus()
    received = []

    def handler(event):
        received.append(event)

    bus.subscribe("TEST_EVENT", handler)
    bus.publish("TEST_EVENT")
    assert len(received) == 1

    bus.unsubscribe("TEST_EVENT", handler)
    bus.publish("TEST_EVENT")
    assert len(received) == 1  # 不再接收
    print("✅ 取消订阅测试通过")


def test_stats():
    """测试统计功能"""
    bus = EventBus()
    bus.publish("TEST_STATS")
    bus.publish("TEST_STATS")

    stats = bus.get_stats()
    assert stats["published_count"] >= 2
    print("✅ 统计功能测试通过")


if __name__ == "__main__":
    test_event_bus_basic()
    test_unsubscribe()
    test_stats()
    print("\n所有测试通过! ✅")
