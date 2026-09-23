"""便签/待办工具模块

功能：
    - 快速创建/编辑/删除便签
    - 标记完成状态
    - 便签持久化存储
    - 支持颜色标记和优先级

Events:
    NOTE_CREATED: 便签创建
    NOTE_DELETED: 便签删除
    NOTE_COMPLETED: 便签完成

Usage:
    from tools.note_tool import NoteManager

    note_manager = NoteManager()
    note = note_manager.create_note("重要会议", "下午3点开会")
    note_manager.complete_note(note.id)
"""

import json
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
from datetime import datetime

from event_bus import event_bus


@dataclass
class Note:
    """便签数据类"""
    id: str
    title: str
    content: str
    created_at: str
    updated_at: str
    completed: bool = False
    color: str = "yellow"    # yellow/blue/green/pink
    priority: str = "normal"  # low/normal/high
    tags: List[str] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


class NoteManager:
    """便签管理器"""

    # 颜色样式
    COLORS = {
        "yellow": {"bg": "#FFF9C4", "border": "#FBC02D"},
        "blue": {"bg": "#BBDEFB", "border": "#1976D2"},
        "green": {"bg": "#C8E6C9", "border": "#388E3C"},
        "pink": {"bg": "#F8BBD0", "border": "#C2185B"},
        "purple": {"bg": "#E1BEE7", "border": "#7B1FA2"},
    }

    def __init__(self, storage_path: str = None):
        self._notes: Dict[str, Note] = {}
        self._storage_path = Path(storage_path) if storage_path else (
            Path.home() / ".pet_demo" / "notes.json"
        )

        # 加载已有便签
        self._load_notes()

    def _load_notes(self):
        """从文件加载便签"""
        if self._storage_path.exists():
            try:
                with open(self._storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for note_data in data:
                        note = Note(**note_data)
                        self._notes[note.id] = note
            except Exception as e:
                print(f"加载便签失败: {e}")

    def _save_notes(self):
        """保存便签到文件"""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = [asdict(note) for note in self._notes.values()]
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存便签失败: {e}")

    # ----- 便签操作 -----

    def create_note(self, title: str, content: str = "",
                   color: str = "yellow", priority: str = "normal",
                   tags: List[str] = None) -> Note:
        """
        创建便签

        Args:
            title: 标题
            content: 内容
            color: 颜色
            priority: 优先级
            tags: 标签列表

        Returns:
            创建的 Note 对象
        """
        now = datetime.now().isoformat()
        note = Note(
            id=str(uuid.uuid4())[:8],
            title=title,
            content=content,
            color=color,
            priority=priority,
            tags=tags or [],
            created_at=now,
            updated_at=now,
        )

        self._notes[note.id] = note
        self._save_notes()

        event_bus.publish("NOTE_CREATED", {
            "id": note.id,
            "title": note.title,
        })

        return note

    def delete_note(self, note_id: str) -> bool:
        """
        删除便签

        Args:
            note_id: 便签ID

        Returns:
            是否删除成功
        """
        if note_id not in self._notes:
            return False

        del self._notes[note_id]
        self._save_notes()

        event_bus.publish("NOTE_DELETED", {"id": note_id})
        return True

    def update_note(self, note_id: str, **kwargs) -> Optional[Note]:
        """
        更新便签

        Args:
            note_id: 便签ID
            **kwargs: 要更新的字段

        Returns:
            更新后的 Note 对象，或 None
        """
        if note_id not in self._notes:
            return None

        note = self._notes[note_id]

        for key, value in kwargs.items():
            if hasattr(note, key):
                setattr(note, key, value)

        note.updated_at = datetime.now().isoformat()
        self._save_notes()

        return note

    def complete_note(self, note_id: str) -> bool:
        """
        标记便签为已完成

        Args:
            note_id: 便签ID

        Returns:
            是否成功
        """
        note = self.update_note(note_id, completed=True)
        if note:
            event_bus.publish("NOTE_COMPLETED", {
                "id": note_id,
                "title": note.title,
            })
            return True
        return False

    def get_note(self, note_id: str) -> Optional[Note]:
        """获取单个便签"""
        return self._notes.get(note_id)

    def get_all_notes(self) -> List[Note]:
        """获取所有便签"""
        return list(self._notes.values())

    def get_pending_notes(self) -> List[Note]:
        """获取未完成的便签"""
        return [n for n in self._notes.values() if not n.completed]

    def get_completed_notes(self) -> List[Note]:
        """获取已完成的便签"""
        return [n for n in self._notes.values() if n.completed]

    def get_notes_by_tag(self, tag: str) -> List[Note]:
        """按标签筛选便签"""
        return [n for n in self._notes.values() if tag in n.tags]

    def search_notes(self, keyword: str) -> List[Note]:
        """搜索便签"""
        keyword = keyword.lower()
        return [
            n for n in self._notes.values()
            if keyword in n.title.lower() or keyword in n.content.lower()
        ]

    def clear_completed(self) -> int:
        """
        清除已完成的便签

        Returns:
            清除的数量
        """
        completed_ids = [n.id for n in self._notes.values() if n.completed]
        for note_id in completed_ids:
            del self._notes[note_id]

        self._save_notes()
        return len(completed_ids)

    def get_statistics(self) -> Dict:
        """获取便签统计信息"""
        all_notes = list(self._notes.values())
        return {
            "total": len(all_notes),
            "completed": sum(1 for n in all_notes if n.completed),
            "pending": sum(1 for n in all_notes if not n.completed),
            "by_color": {
                color: sum(1 for n in all_notes if n.color == color)
                for color in self.COLORS.keys()
            },
        }


# 便捷函数
def create_note_manager(storage_path: str = None) -> NoteManager:
    """创建便签管理器"""
    return NoteManager(storage_path)
