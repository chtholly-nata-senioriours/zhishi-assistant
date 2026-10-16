"""动画控制器模块

管理和播放桌宠的各种动画效果。
支持动画类型：
    thumbs_up, yawn, sleep, wave, think, happy, confused

Animation Format:
    - GIF 文件: assets/*.gif
    - 精灵图: assets/sprites/*.png
    - 数值动画: 使用 QPropertyAnimation

职责：
    1. 加载和缓存动画资源
    2. 管理和切换动画状态
    3. 提供动画播放器接口 (GIF / 图片 / 数值动画)
    4. 支持动画优先级和队列
"""

import os
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

from PySide6.QtWidgets import QLabel, QWidget
from PySide6.QtCore import QTimer, Qt, QObject, Signal, QPoint, QSize, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QMovie, QPixmap

from event_bus import event_bus


@dataclass
class Animation:
    """动画资源定义"""
    name: str                    # 动画标识名
    type: str                    # 动画类型 (gif/spritesheet/image/numeric)
    file_path: Optional[str]    # 文件路径
    duration: int = 1000        # 持续时间 (毫秒)
    loop_count: int = 0         # 循环次数 (0=无限)
    priority: int = 0           # 优先级 (越高越优先)
    speed: int = 100            # 播放速度百分比 (100=正常, 50=半速)
    frames: int = 1             # 精灵图总帧数
    frame_width: int = 0        # 精灵图每帧宽度 (0=自动=图片高度)


class AnimController(QObject):
    """动画控制器 - 统一管理动画资源和播放

    支持三种动画类型：
      1. GIF 动画 (type='gif')
      2. 静态图片 (type='image')
      3. 数值动画 (type='numeric') - 使用 QTimer + 属性修改实现

    动画定义中包含额外参数，用于数值动画：
      - scale: (start, end) 缩放范围
      - rotation: (start, end) 旋转角度范围
      - opacity: (start, end) 透明度范围
      - text: 动画同时显示的气泡文字
    """

    # 信号
    animation_started = Signal(str)      # 动画名称
    animation_finished = Signal(str)
    frame_changed = Signal(int)
    text_requested = Signal(str, float)     # 文字内容, 显示时长(秒)
    _play_requested = Signal(str)           # 跨线程安全播放请求

    # 动画优先级定义
    PRIORITY = {
        "high": 10,         # 用户交互触发的动画
        "normal": 5,        # 状态变化触发的动画
        "low": 1,           # 背景动画
        "idle": 0,          # 空闲动画
    }

    def __init__(self, parent=None):
        super().__init__(parent)

        # 动画资源库 {name: Animation}
        self._animations: Dict[str, Animation] = {}

        # 当前播放的动画
        self._current_anim: Optional[Animation] = None
        self._current_movie: Optional[QMovie] = None

        # 动画队列
        self._queue: List[Animation] = []

        # 关联的 QLabel（用于显示GIF/图片）
        self._target_label = None

        # 关联的 QWidget（用于数值动画）
        self._target_widget = None

        # 默认静态图片路径（动画结束后恢复）
        self._default_image = None

        # 动画恢复用的原始状态
        self._original_size = None
        self._original_geometry = None
        self._original_opacity = None

        # 当前精灵图动画定时器
        self._spritesheet_timer = None

        # 当前数值动画定时器
        self._numeric_timer = None

        # 位移类数值动画（摇一摇 / 弹跳）开始时的窗口位置。
        # 动画被打断（用户按住了窗口）时必须靠它把窗口放回原处 ——
        # 否则会永久停在「摇到一半」的偏移位置上。
        self._numeric_origin = None

        # 当前超时定时器（用于 loop_count=0 的 GIF/spritesheet/image 动画自动结束）
        self._timeout_timer = None

        # 状态→持续动画映射（状态切换时自动播放对应动画）
        self._state_anim = "idle"

        # 防重入锁：防止 _on_anim_finished 递归调用 play
        self._transitioning = False

        # 跨线程播放请求信号（QueuedConnection 确保在主线程执行 Qt 操作）
        self._play_requested.connect(self._on_play_requested, Qt.ConnectionType.QueuedConnection)

        # 初始化内置动画
        self._setup_builtin_animations()

        # 加载 assets 目录
        self._load_assets()

        # 注册事件监听
        self._setup_event_listeners()


    def _setup_builtin_animations(self):
        """设置默认动画定义（含数值动画参数）"""
        builtin_def = [
            # (name, type, file, dur_ms, priority, extra_dict)
            # --- 用户交互 (高优先级) ---
            ("wave", "numeric", None, 1200, 10, {
                "rotation": (-15, 15), "rotation_repeat": 4,
                "text": "嗨~", "text_duration": 2.0,
                "speed": 50,
            }),
            ("happy", "numeric", None, 500, 10, {
                "bounce_offset": 5, "bounce_repeat": 3,
                "text": "耶~", "text_duration": 2.0,
            }),
            # --- 状态变化 (中优先级) ---
            ("thumbs_up", "numeric", None, 500, 5, {
                "scale": (1.0, 1.15), "scale_repeat": 2,
                "text": "加油！", "text_duration": 2.0,
            }),
            ("yawn", "numeric", None, 800, 5, {
                "rotation": (-5, 5), "rotation_repeat": 3,
                "text": "哈~欠", "text_duration": 2.0,
            }),
            ("confused", "numeric", None, 700, 5, {
                "rotation": (-10, 10), "rotation_repeat": 3,
                "text": "嗯？", "text_duration": 2.0,
            }),
            ("think", "numeric", None, 1000, 4, {
                "scale": (1.0, 1.05), "scale_repeat": 4,
                "text": "嗯...", "text_duration": 2.0,
            }),
            ("sleep", "numeric", None, 3000, 3, {
                "opacity": (0.9, 0.4),
                "text": "Zzz...", "text_duration": 3.0,
            }),
            # --- 空闲 (低优先级) ---
            ("idle", "numeric", None, 8000, 0, {"speed": 10}),
        ]

        for name, a_type, fpath, dur, prio, extra in builtin_def:
            anim = Animation(name, a_type, fpath, duration=dur, priority=prio)
            if extra:
                # 把 extra 中支持的字段同步到 Animation 属性上
                for attr in ("speed",):
                    if attr in extra:
                        setattr(anim, attr, extra[attr])
                object.__setattr__(anim, "extra", extra)
            self._animations[anim.name] = anim

    def _get_assets_dir(self) -> Path:
        """获取资源目录"""
        return Path(__file__).parent / "assets"

    def _load_assets(self, asset_dir: Path = None):
        """加载 assets 目录下的动画资源

        Args:
            asset_dir: 指定资源目录，None 则使用默认
        """
        assets_dir = asset_dir or self._get_assets_dir()
        if not assets_dir.exists():
            return

        # 清空旧的 GIF/PNG 动画条目（保留内置 numeric 动画）
        keys_to_remove = [
            k for k, v in self._animations.items()
            if v.type in ("gif", "image")
        ]
        for k in keys_to_remove:
            del self._animations[k]

        # 加载 GIF 文件
        for gif_file in assets_dir.glob("*.gif"):
            name = gif_file.stem
            if name not in self._animations:
                self._animations[name] = Animation(
                    name=name,
                    type="gif",
                    file_path=str(gif_file),
                    priority=3,
                )
            else:
                # 更新现有动画的路径
                self._animations[name].file_path = str(gif_file)
                self._animations[name].type = "gif"

        # 加载 PNG 图片（检测精灵图：多帧水平排列）
        for png_file in assets_dir.glob("*.png"):
            name = png_file.stem
            # 检查是否为精灵图（水平排列的多帧）
            pixmap = QPixmap(str(png_file))
            is_spritesheet = False
            fw, frames = 0, 1
            if not pixmap.isNull():
                w, h = pixmap.width(), pixmap.height()
                # 精灵图检测条件：宽度至少是高度的1.5倍，且能被常见帧数整除
                if w >= h * 1.5:
                    # 尝试按帧数分割：优先匹配 4 帧（最常见），再降序试其他
                    for n in (4, 2, 3, 5, 6, 8):
                        if w % n == 0:
                            fw = w // n
                            frames = n
                            # 额外验证：每帧宽度应该接近高度（正方形帧）
                            if fw >= h * 0.8 and fw <= h * 1.2:
                                is_spritesheet = True
                                break

            if name not in self._animations:
                anim = Animation(
                    name=name,
                    type="spritesheet" if is_spritesheet else "image",
                    file_path=str(png_file),
                    priority=3,
                    frames=frames,
                    frame_width=fw,
                )
                self._animations[name] = anim
            else:
                # 更新现有动画（覆盖内置定义的优先级，避免被低优先级卡住）
                self._animations[name].file_path = str(png_file)
                self._animations[name].frames = frames
                self._animations[name].frame_width = fw
                self._animations[name].priority = 5
                if is_spritesheet:
                    # 精灵图文件存在时，将类型改为 spritesheet（覆盖 numeric 定义）
                    self._animations[name].type = "spritesheet"
                else:
                    # 非精灵图时，如果原类型是 numeric，则保留 numeric
                    # 否则改为 image
                    if self._animations[name].type not in ("numeric",):
                        self._animations[name].type = "image"

        # 调试日志：打印所有动画配置
        print("[AnimController] 动画加载完成:")
        for name, anim in sorted(self._animations.items()):
            print(f"  {name}: type={anim.type}, frames={anim.frames}, "
                  f"duration={anim.duration}ms, priority={anim.priority}, "
                  f"file={anim.file_path or 'None'}")

    def _setup_event_listeners(self):
        """设置事件监听器"""
        event_bus.subscribe("REQUEST_ANIMATION", self._on_request_animation)
        event_bus.subscribe("STATE_CHANGE", self._on_state_change)

    # 状态→持续动画映射
    STATE_ANIM_MAP = {
        "idle":  "idle",
        "relax": "yawn",
        "sleep": "sleep",
    }

    def _on_state_change(self, event):
        """状态变更时更新持续动画"""
        data = event.get("data", {})
        to_state = data.get("to", "")
        anim = self.STATE_ANIM_MAP.get(to_state)
        if anim and anim != self._state_anim:
            print(f"[AnimController] 状态动画: {self._state_anim} -> {anim} (state={to_state})")
            self._state_anim = anim
            # 通过 QueuedConnection 信号跨线程安全播放
            self._play_requested.emit(anim)

    def _on_play_requested(self, anim_name: str):
        """跨线程安全播放（由信号触发，始终在主线程执行）"""
        self.play(anim_name, force=True)

    def set_target(self, label: QLabel, default_image: str = None, asset_dir: str = None):
        """
        设置动画显示的目标 QLabel（用于 GIF/图片 播放）

        Args:
            label: 用于显示动画的 QLabel
            default_image: 动画结束时恢复的默认图片路径
            asset_dir: 动画资源目录（用于加载 GIF/PNG），None 或空字符串则使用默认
        """
        self._target_label = label
        self._default_image = default_image
        if asset_dir:
            self._load_assets(Path(asset_dir))

    def reload_assets(self, asset_dir: str, default_image: str = None):
        """
        重新加载动画资源和默认图片（用于切换宠物模型）

        Args:
            asset_dir: 新的动画资源目录
            default_image: 新的默认图片路径
        """
        self._default_image = default_image
        self._load_assets(Path(asset_dir))

    def play(self, anim_name: str, force: bool = False) -> bool:
        """
        播放指定动画

        Args:
            anim_name: 动画名称
            force: 是否强制播放（中断当前动画）

        Returns:
            是否成功开始播放
        """
        if anim_name not in self._animations:
            print(f"动画不存在: {anim_name}")
            return False

        anim = self._animations[anim_name]

        # 正在播放同一动画则跳过（避免重复触发）
        if self._current_anim and self._current_anim.name == anim_name:
            return True

        print(f"[AnimController] play('{anim_name}') type={anim.type}, "
              f"current={self._current_anim.name if self._current_anim else 'None'}")

        # 检查优先级
        if self._current_anim and not force:
            if anim.priority < self._current_anim.priority:
                # 当前动画优先级更高，加入队列（去重）
                if not any(q.name == anim_name for q in self._queue):
                    self._queue.append(anim)
                return False

        # 停止当前动画
        self._stop_current()

        # 播放新动画
        self._current_anim = anim
        self.animation_started.emit(anim_name)

        if anim.type == "spritesheet" and anim.file_path:
            self._play_spritesheet(anim)
        elif anim.type == "gif" and anim.file_path:
            self._play_gif(anim)
        elif anim.type == "image" and anim.file_path:
            self._play_image(anim)
        else:
            self._play_numeric(anim)

        return True

    def _play_gif(self, anim: Animation):
        """播放GIF动画"""
        if not self._target_label:
            return

        self._current_movie = QMovie(anim.file_path)
        self._current_movie.setCacheMode(QMovie.CacheMode.CacheAll)

        # 设置播放速度（控制 GIF 快慢）
        if anim.speed != 100:
            self._current_movie.setSpeed(anim.speed)

        # 连接信号
        self._current_movie.frameChanged.connect(self._on_frame_changed)

        # 设置循环和完成回调
        if anim.loop_count > 0:
            self._current_movie.setLoopCount(anim.loop_count)
            self._current_movie.finished.connect(self._on_anim_finished)

        self._target_label.setMovie(self._current_movie)
        self._current_movie.start()

        # 无限循环 GIF，用定时器超时停止
        if anim.loop_count == 0 and anim.duration > 0:
            self._timeout_timer = QTimer(self)
            self._timeout_timer.setSingleShot(True)
            self._timeout_timer.timeout.connect(self._on_anim_finished)
            self._timeout_timer.start(anim.duration)

    def _play_image(self, anim: Animation):
        """显示静态图片"""
        if not self._target_label:
            return

        pixmap = QPixmap(anim.file_path)
        if not pixmap.isNull():
            self._target_label.setPixmap(
                pixmap.scaled(self._target_label.size(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
            )

        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_anim_finished)
        self._timeout_timer.start(anim.duration)

    def _play_spritesheet(self, anim: Animation):
        """播放精灵图动画 - 水平排列的多帧 PNG，逐帧裁剪显示"""
        if not self._target_label:
            return

        spritesheet = QPixmap(anim.file_path)
        if spritesheet.isNull():
            return

        fw = anim.frame_width if anim.frame_width > 0 else spritesheet.height()
        fh = spritesheet.height()
        total = max(anim.frames, 1)
        interval = max(anim.duration // total, 16) if anim.duration > 0 else 100
        frame_idx = [0]  # 用列表绕过 nonlocal 作用域限制
        # 固定缩放尺寸：取父窗口内容区大小（减去布局边距），确保不受 label 当前尺寸影响
        if self._target_label.parent():
            parent_size = self._target_label.parent().size()
            target_size = QSize(parent_size.width() - 20, parent_size.height() - 20)
        else:
            target_size = self._target_label.size()

        # 应用速度倍率（仅用于调节帧间隔，但不能超过 duration/frames 的自然间隔）
        if anim.speed != 100:
            adjusted = int(interval * 100 / anim.speed)
            # 精灵图帧间隔不应超过自然间隔（避免 speed 过低导致帧间隔 > duration）
            natural_interval = max(anim.duration // total, 16) if anim.duration > 0 else 100
            interval = min(adjusted, natural_interval)

        print(f"[AnimController] _play_spritesheet('{anim.name}'): "
              f"fw={fw}, fh={fh}, frames={total}, interval={interval}ms, "
              f"duration={anim.duration}ms, loop_count={anim.loop_count}")

        def tick():
            idx = frame_idx[0]
            x = idx * fw
            frame = spritesheet.copy(x, 0, fw, fh)
            if not frame.isNull():
                self._target_label.setPixmap(
                    frame.scaled(target_size,
                                 Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
                )
            self.frame_changed.emit(idx)
            frame_idx[0] = (idx + 1) % total
            if frame_idx[0] == 0 and anim.loop_count > 0:
                self._on_anim_finished()

        timer = QTimer(self)
        timer.timeout.connect(tick)
        timer.start(interval)
        self._spritesheet_timer = timer
        tick()

        # 无限循环 spritesheet，用定时器超时停止（与 GIF 处理方式一致）
        if anim.loop_count == 0 and anim.duration > 0:
            self._timeout_timer = QTimer(self)
            self._timeout_timer.setSingleShot(True)
            self._timeout_timer.timeout.connect(self._on_anim_finished)
            self._timeout_timer.start(anim.duration)

    def _play_numeric(self, anim: Animation):
        """播放数值动画

        如果动画定义包含 extra 参数（如 scale, rotation, opacity），
        则执行对应的动画效果。否则仅恢复默认图片。
        """
        extra = getattr(anim, "extra", {}) or {}

        # 显示气泡文字
        if extra.get("text"):
            self.text_requested.emit(extra["text"], extra.get("text_duration", 2.0))

        # 执行数值动画效果
        if extra.get("scale"):
            self._numeric_scale(extra["scale"], extra.get("scale_repeat", 1), anim.duration)
        elif extra.get("rotation"):
            self._numeric_rotate(extra["rotation"], extra.get("rotation_repeat", 1), anim.duration)
        elif extra.get("opacity"):
            self._numeric_opacity(extra["opacity"], anim.duration)
        elif extra.get("bounce_offset"):
            self._numeric_bounce(extra["bounce_offset"], extra.get("bounce_repeat", 1), anim.duration)
        else:
            # 无数值效果，仅恢复默认图片
            self._restore_default_image()

        self.frame_changed.emit(0)
        QTimer.singleShot(anim.duration, self._on_anim_finished)

    def _restore_default_image(self):
        """恢复默认静态图片"""
        if self._default_image and self._target_label:
            pixmap = QPixmap(self._default_image)
            if not pixmap.isNull():
                self._target_label.setPixmap(
                    pixmap.scaled(self._target_label.size(),
                                  Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
                )

    # -- 数值动画效果 (使用 QTimer 实现) --

    def _numeric_scale(self, scale_range: tuple, repeat: int, duration_ms: int):
        """缩放动画 - 通过定时器改变窗口大小"""
        if not self._target_widget:
            return
        widget = self._target_widget

        # 保存原始大小
        if self._original_size is None:
            self._original_size = widget.size()

        total = repeat * 2  # 放大→缩小 为一个周期
        step = 0

        def tick():
            nonlocal step
            step += 1
            if step > total:
                timer.stop()
                if self._original_size:
                    widget.setFixedSize(self._original_size)
                return
            # 交替放大和缩小
            factor = scale_range[0] if step % 2 == 1 else scale_range[1]
            new_w = int(self._original_size.width() * factor)
            new_h = int(self._original_size.height() * factor)
            widget.setFixedSize(new_w, new_h)

        timer = QTimer(self)
        timer.timeout.connect(tick)
        timer.start(duration_ms // total)
        self._numeric_timer = timer

    def _numeric_rotate(self, rotation_range: tuple, repeat: int, duration_ms: int):
        """旋转动画 - 通过改变窗口位置实现摇一摇效果"""
        if not self._target_widget:
            return
        widget = self._target_widget

        original_pos = widget.pos()
        self._numeric_origin = original_pos
        total = repeat * 2
        step = 0

        def tick():
            nonlocal step
            step += 1
            if step > total:
                timer.stop()
                widget.move(original_pos)
                self._numeric_origin = None
                return
            # 左右摇摆
            angle = rotation_range[0] if step % 2 == 1 else rotation_range[1]
            offset = QPoint(angle * 2, 0)
            widget.move(original_pos + offset)

        timer = QTimer(self)
        timer.timeout.connect(tick)
        timer.start(duration_ms // total)
        self._numeric_timer = timer

    def _numeric_opacity(self, opacity_range: tuple, duration_ms: int):
        """透明度动画 - 修改窗口透明度"""
        if not self._target_widget:
            return
        widget = self._target_widget

        # 保存原始透明度
        if self._original_opacity is None:
            self._original_opacity = widget.windowOpacity()

        target_opacity = opacity_range[1]
        widget.setWindowOpacity(target_opacity)

        # 恢复透明度
        def restore():
            if widget and self._original_opacity is not None:
                widget.setWindowOpacity(self._original_opacity)
                self._original_opacity = None

        QTimer.singleShot(duration_ms, restore)

    def _numeric_bounce(self, bounce_offset: int, repeat: int, duration_ms: int):
        """弹跳动画 - 上下移动"""
        if not self._target_widget:
            return
        widget = self._target_widget

        original_pos = widget.pos()
        self._numeric_origin = original_pos
        total = repeat * 2
        step = 0

        def tick():
            nonlocal step
            step += 1
            if step > total:
                timer.stop()
                widget.move(original_pos)
                self._numeric_origin = None
                return
            # 上下弹跳
            offset_y = -bounce_offset if step % 2 == 1 else bounce_offset
            widget.move(original_pos.x(), original_pos.y() + offset_y)

        timer = QTimer(self)
        timer.timeout.connect(tick)
        timer.start(duration_ms // total)
        self._numeric_timer = timer

    def set_target_widget(self, widget: QWidget):
        """设置数值动画的目标窗口控件"""
        self._target_widget = widget

    def stop(self):
        """停止当前动画"""
        self._stop_current()

    def _stop_current(self):
        """停止当前播放的动画"""
        if self._current_movie:
            self._current_movie.stop()
            self._current_movie = None

        self._current_anim = None
        self._stop_timeout_timer()
        self._stop_spritesheet()
        self._stop_numeric()

    def _stop_spritesheet(self):
        """停止精灵图动画定时器"""
        if self._spritesheet_timer:
            self._spritesheet_timer.stop()
            self._spritesheet_timer = None

    def _stop_timeout_timer(self):
        """停止超时定时器（GIF/spritesheet/image 的 duration 超时）"""
        if self._timeout_timer:
            self._timeout_timer.stop()
            self._timeout_timer = None

    def _stop_numeric(self):
        """停止数值动画 - 停止当前数值动画定时器并恢复初始状态"""
        if self._numeric_timer:
            self._numeric_timer.stop()
            self._numeric_timer = None
        # 位移类动画被打断 → 把窗口放回开始时的位置。
        # 不做的话窗口会永久停在偏移位置上（摇到一半的样子）。
        if self._numeric_origin is not None and self._target_widget:
            self._target_widget.move(self._numeric_origin)
        self._numeric_origin = None
        if self._original_size and self._target_widget:
            self._target_widget.setFixedSize(self._original_size)
            self._original_size = None

    def _on_frame_changed(self, frame_number: int):
        """GIF帧变化回调"""
        self.frame_changed.emit(frame_number)

    def _on_anim_finished(self):
        """动画完成回调"""
        if self._transitioning:
            return
        self._transitioning = True
        try:
            finished_name = self._current_anim.name if self._current_anim else ""
            print(f"[AnimController] 动画结束: {finished_name}, state_anim={self._state_anim}")
            self._stop_current()

            if finished_name:
                self.animation_finished.emit(finished_name)

            # 播放队列中的下一个动画
            if self._queue:
                next_anim = self._queue.pop(0)
                self.play(next_anim.name, force=True)
            elif finished_name and finished_name == self._state_anim:
                # 状态动画（idle/yawn/sleep）续播，不恢复默认图
                self.play(self._state_anim, force=True)
            else:
                # 非状态动画结束，恢复默认图片
                self._restore_default_image()
        finally:
            self._transitioning = False

    def _on_request_animation(self, event):
        """处理动画请求事件"""
        data = event.get("data", {})
        anim_type = data.get("type", "")
        if anim_type:
            # 通过信号跨线程安全执行（QueuedConnection 确保在主线程执行）
            self._play_requested.emit(anim_type)

    def get_animation_list(self) -> List[str]:
        """获取所有可用动画列表"""
        return list(self._animations.keys())

    def get_current_animation(self) -> Optional[str]:
        """获取当前播放的动画名称"""
        if self._current_anim:
            return self._current_anim.name
        return None

    def clear_queue(self):
        """清空动画队列"""
        self._queue.clear()


# 便捷函数
def create_anim_controller() -> AnimController:
    """创建动画控制器实例"""
    return AnimController()
