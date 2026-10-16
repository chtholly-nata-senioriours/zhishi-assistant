"""事件总线核心模块

提供基于发布-订阅模式的事件通信机制，所有模块通过事件总线进行解耦通信。

标准事件格式:
    {
        "type": "事件类型",
        "data": {...},       # 附加数据
        "timestamp": float    # 时间戳
    }

Usage:
    from event_bus import event_bus

    # 订阅事件
    def on_timer_end(event):
        print(f"Timer ended: {event['data']}")
    event_bus.subscribe("TIMER_END", on_timer_end)

    # 发布事件
    event_bus.publish("TIMER_END", {"duration": 25})

    # 取消订阅
    event_bus.unsubscribe("TIMER_END", on_timer_end)
"""

import time
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Any
from threading import Lock

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 允许的事件类型注册表（避免拼写错误）
ALLOWED_EVENTS = {
    # 感知层事件
    "KEYBOARD_HIGH_RATE",
    "MOUSE_MOVE",
    "MOUSE_CLICK",
    "MOUSE_CLICK_PET",
    "WINDOW_ACTIVE",
    "TIME_30MIN",
    "TIME_HOURLY",
    "TIME_TICK",

    # 状态机事件
    "STATE_CHANGE",
    "STATE_ENTER",
    "STATE_EXIT",

    # 工具层事件
    "TIMER_START",
    "TIMER_END",
    "TIMER_TICK",
    "TIMER_PAUSE",
    "TIMER_RESUME",
    "NOTE_CREATED",
    "NOTE_DELETED",
    "QUICK_LAUNCH",

    # 交互事件
    "USER_INPUT",
    "AI_REPLY",

    # AI 事件（v2 功能优先改造新增）
    "AI_REQUEST",        # 用户发起一次 AI 请求
    "AI_CHUNK",          # 流式增量
    "AI_DONE",           # 完成
    "AI_ERROR",          # 出错
    "AI_CANCEL",         # 取消
    "HOTKEY_TRIGGERED",  # 全局热键触发
    "PET_CLICKED",
    "PET_DRAGGED",
    "PET_MENU_OPEN",
    "PET_MENU_CLOSE",

    # 系统事件
    "APP_START",
    "APP_STOP",
    "CONFIG_CHANGED",
    "SOUND_MUTE",
    "SOUND_UNMUTE",
    "PET_SHOW",
    "PET_HIDE",

    # 规则引擎输出事件
    "REQUEST_ANIMATION",
    "REQUEST_SOUND",
}


class EventBus:
    """事件总线 - 全局事件发布订阅中心"""

    def __init__(self):
        # _subscribers: {event_type: [callback1, callback2, ...]}
        self._subscribers: Dict[str, List[Callable]] = {}
        self._lock = Lock()
        # 统计信息
        self._stats = {
            "published_count": 0,
            "dropped_count": 0,
            "start_time": time.time(),
        }

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """
        订阅指定类型的事件

        Args:
            event_type: 事件类型字符串
            callback: 事件触发时调用的回调函数，接收 event 字典参数
        """
        if event_type not in ALLOWED_EVENTS:
            logger.warning(f"订阅未注册的事件类型: {event_type}")

        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            if callback not in self._subscribers[event_type]:
                self._subscribers[event_type].append(callback)
                logger.debug(f"订阅事件: {event_type}, 当前订阅数: {len(self._subscribers[event_type])}")

    def unsubscribe(self, event_type: str, callback: Callable) -> bool:
        """
        取消订阅指定类型的事件

        Args:
            event_type: 事件类型字符串
            callback: 要移除的回调函数

        Returns:
            是否成功移除
        """
        with self._lock:
            if event_type in self._subscribers and callback in self._subscribers[event_type]:
                self._subscribers[event_type].remove(callback)
                logger.debug(f"取消订阅: {event_type}")
                return True
            return False

    def publish(self, event_type: str, data: Any = None) -> Dict:
        """
        发布事件到总线

        构造标准事件格式并分发给所有订阅者。
        订阅者在独立线程中执行以避免阻塞发布者。

        Args:
            event_type: 事件类型
            data: 事件附加数据

        Returns:
            构造的事件字典
        """
        if event_type not in ALLOWED_EVENTS:
            logger.warning(f"发布未注册的事件类型: {event_type}")
            self._stats["dropped_count"] += 1

        event = {
            "type": event_type,
            "data": data or {},
            "timestamp": time.time(),
        }

        with self._lock:
            callbacks = list(self._subscribers.get(event_type, []))
            self._stats["published_count"] += 1

        # 执行回调（在锁外执行避免阻塞）
        for callback in callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"事件处理异常 [{event_type}]: {e}", exc_info=True)

        return event

    def publish_async(self, event_type: str, data: Any = None) -> Dict:
        """异步投递事件：订阅者在线程池中执行，绝不阻塞发布者。

        T2 改造新增。用于 AI 请求等耗时操作 —— publish() 是同步 for 循环，
        若发布者本身是 pynput 监听线程或状态机线程，在回调里同步发 HTTP
        会直接冻结感知层。高频感知事件（MOUSE_MOVE 等）仍应用同步 publish()。

        Args:
            event_type: 事件类型
            data: 事件附加数据

        Returns:
            构造的事件字典（回调尚未执行完）
        """
        if event_type not in ALLOWED_EVENTS:
            logger.warning(f"发布未注册的事件类型: {event_type}")
            self._stats["dropped_count"] += 1

        event = {
            "type": event_type,
            "data": data or {},
            "timestamp": time.time(),
        }

        with self._lock:
            callbacks = list(self._subscribers.get(event_type, []))
            self._stats["published_count"] += 1

        for callback in callbacks:
            _executor.submit(self._safe_call, callback, event, event_type)

        return event

    @staticmethod
    def _safe_call(callback: Callable, event: Dict, event_type: str) -> None:
        """线程池内执行回调，异常只记日志不外抛。"""
        try:
            callback(event)
        except Exception as e:
            logger.error(f"事件处理异常 [{event_type}]: {e}", exc_info=True)

    def get_stats(self) -> Dict:
        """获取事件统计信息"""
        return dict(self._stats)

    def get_subscriber_count(self, event_type: str = None) -> int:
        """
        获取订阅者数量

        Args:
            event_type: 指定事件类型，None表示所有事件

        Returns:
            订阅者数量
        """
        if event_type:
            return len(self._subscribers.get(event_type, []))
        return sum(len(cbs) for cbs in self._subscribers.values())

    def list_event_types(self) -> List[str]:
        """列出所有有订阅者的事件类型"""
        with self._lock:
            return [et for et, cbs in self._subscribers.items() if cbs]


# 异步投递线程池（publish_async 使用）
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ebus")


# 全局事件总线实例
event_bus = EventBus()

# 注册新事件类型的辅助函数
def register_event_type(event_type: str) -> bool:
    """
    注册新的事件类型

    Args:
        event_type: 要注册的事件类型字符串

    Returns:
        如果已存在返回False，否则返回True
    """
    if event_type in ALLOWED_EVENTS:
        return False
    ALLOWED_EVENTS.add(event_type)
    logger.info(f"注册新事件类型: {event_type}")
    return True
