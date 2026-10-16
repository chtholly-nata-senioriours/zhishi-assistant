# -*- coding: utf-8 -*-
"""AI 服务配置表单 —— 对话框与控制中心「AI 服务」页共用的**同一份**实现。

为什么抽出来
    以前这套字段只存在于 `AISettingsDialog` 里。控制中心也要一份时，
    复制一遍必然导致两处漂移（改了模型列表忘了改另一边）。
    抽成 `AIConfigForm` 后，宿主只负责提供按钮与摆放位置。

线程模型（硬规则：主线程不可阻塞）
    「测试连接」要发真实网络请求，必须放子线程。
    用 `ThreadPoolExecutor` + Qt Signal，与 `SessionManager` 同一套模式：
    信号跨线程投递由 Qt 自动排队，UI 侧不需要加锁。

为什么探测逻辑不在这里
    它在 `engine/ai/probe.py`（纯 Python、零 Qt），于是能被单测，
    也能被 `spikes/api_check.py` 复用 —— 一处实现两处用。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from data import key_store
from data.config_manager import config_manager
from data.log_manager import log_manager
from engine.ai.probe import ProbeResult, probe as probe_api
from presentation.design.theme import theme
from presentation.design.tokens import SPACING
from presentation.design.widgets import Button, IconButton, SegmentedControl

# 探测线程池：单线程即可（用户一次只点一个「测试连接」）
_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aiprobe")


# ============================================================
# 服务商预设
# ============================================================

@dataclass
class ProviderPreset:
    id: str
    name: str
    base_url: str
    models: List[str] = field(default_factory=list)
    vision_models: List[str] = field(default_factory=list)
    note: str = ""


# 全部走 OpenAI 兼容协议，所以只需要一个 base_url + 模型名。
# 模型名只是**候选**（下拉可编辑），地址以服务商文档为准 —— 这里给的是常用值。
PROVIDERS: List[ProviderPreset] = [
    ProviderPreset(
        "siliconflow", "硅基流动 SiliconFlow",
        "https://api.siliconflow.cn/v1",
        models=["inclusionAI/Ling-flash-2.0", "Qwen/Qwen3-8B",
                "deepseek-ai/DeepSeek-V3", "Qwen/Qwen3-235B-A22B",
                "moonshotai/Kimi-K2-Instruct"],
        vision_models=["Qwen/Qwen3-VL-32B-Instruct", "Qwen/Qwen3-VL-30B-A3B-Instruct",
                       "PaddlePaddle/PaddleOCR-VL-1.5", "Qwen/Qwen3-VL-8B-Instruct"],
        note="聚合平台：一个 Key 调多个厂商模型；模型名必须带命名空间前缀。"
             "视觉模型实测延迟差异极大（见 tooltip），别按参数量猜快慢",
    ),
    ProviderPreset(
        "deepseek", "DeepSeek 官方",
        "https://api.deepseek.com/v1",
        models=["deepseek-chat", "deepseek-reasoner"],
        vision_models=[],
        note="官方无视觉模型，截图问答（Alt+S）需另配视觉模型",
    ),
    ProviderPreset(
        "openai", "OpenAI",
        "https://api.openai.com/v1",
        models=["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
        vision_models=["gpt-4o-mini", "gpt-4o"],
        note="国内网络通常需要代理",
    ),
    ProviderPreset(
        "dashscope", "阿里云百炼（通义）",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        models=["qwen-plus", "qwen-turbo", "qwen-max"],
        vision_models=["qwen-vl-plus", "qwen-vl-max"],
        note="使用「OpenAI 兼容模式」端点，不是 DashScope 原生端点",
    ),
    ProviderPreset(
        "moonshot", "月之暗面 Kimi",
        "https://api.moonshot.cn/v1",
        models=["moonshot-v1-8k", "moonshot-v1-32k"],
        vision_models=["moonshot-v1-8k-vision-preview"],
    ),
    ProviderPreset(
        "ollama", "本地 Ollama（零成本）",
        "http://localhost:11434/v1",
        models=["qwen2.5:7b", "llama3.2:3b"],
        vision_models=["llava:7b", "qwen2.5vl:7b"],
        note="本地推理，无需 api_key；需先 ollama serve",
    ),
    ProviderPreset(
        "custom", "自定义（任意 OpenAI 兼容服务）",
        "",
        note="填写形如 https://host/v1 的地址（不要带 /chat/completions）",
    ),
]


class _ProbeBridge(QObject):
    """把子线程的探测结果送回主线程（Qt 信号跨线程自动排队）。

    为什么是**模块级单例**而不是每个表单一个
        探测跑在子线程里，宿主可能先被关掉。若 bridge 的生命周期跟着
        宿主走，子线程 emit 时对象已销毁 → RuntimeError。
        做成进程级单例后，宿主只负责 connect / disconnect，
        关掉宿主就断开连接，迟到的结果自然无人接收（安全）。
    """

    done = Signal(object)          # ProbeResult


_BRIDGE = _ProbeBridge()


# ============================================================
# 表单
# ============================================================

class AIConfigForm(QWidget):
    """AI 服务配置字段 + 状态区。宿主提供按钮。"""

    applied = Signal()
    busy_changed = Signal(bool)

    def __init__(self, parent=None, config=None,
                 busy_check: Optional[Callable[[], bool]] = None):
        super().__init__(parent)
        self._cfg = config or config_manager
        self._busy_check = busy_check
        self._testing = False
        self._loading = True
        self._initial_key = ""
        self._keyring_mode = False
        self._probe_connected = False

        self._build_ui()
        self.load_from_config()
        self._loading = False

    # ------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACING["md"])

        form = QFormLayout()
        form.setSpacing(SPACING["sm"])
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._preset_combo = QComboBox()
        for p in PROVIDERS:
            self._preset_combo.addItem(p.name, p.id)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        form.addRow("服务商", self._preset_combo)

        self._base_url_edit = QLineEdit()
        self._base_url_edit.setPlaceholderText("https://api.example.com/v1")
        form.addRow("接口地址", self._base_url_edit)

        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setToolTip("问答 / 翻译使用的模型（纯文本即可）")
        form.addRow("文本模型", self._model_combo)

        self._vision_combo = QComboBox()
        self._vision_combo.setEditable(True)
        self._vision_combo.setToolTip("截图问答（Alt+S）使用的模型，必须能看图")
        form.addRow("视觉模型", self._vision_combo)

        key_row = QWidget()
        key_lay = QHBoxLayout(key_row)
        key_lay.setContentsMargins(0, 0, 0, 0)
        key_lay.setSpacing(SPACING["sm"])
        self._key_edit = QLineEdit()
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setPlaceholderText("sk-…（本地服务如 Ollama 可留空）")
        self._btn_show_key = IconButton("eye", "显示 / 隐藏密钥")
        self._btn_show_key.setCheckable(True)
        self._btn_show_key.toggled.connect(self._on_toggle_key)
        key_lay.addWidget(self._key_edit, 1)
        key_lay.addWidget(self._btn_show_key)
        form.addRow("API Key", key_row)

        # 保存位置：密钥库优先。明文那一档是**给老用户与无密钥库机器**的退路，
        # 选它就该让它看起来像退路（标签写清楚代价），不要做成并列的普通选项。
        self._key_mode = SegmentedControl(["系统密钥库", "配置文件（明文）"])
        self._key_mode.setToolTip(
            "系统密钥库：由操作系统按当前用户保管，配置文件里只留一个引用。\n"
            "配置文件（明文）：兼容老配置；密钥会随备份与「导出全部数据」被带走。\n"
            f"当前状态：{key_store.status()}")
        self._key_mode.changed.connect(self._on_key_mode_changed)
        form.addRow("保存位置", self._key_mode)

        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(10, 600)
        self._timeout_spin.setSuffix(" 秒")
        self._timeout_spin.setToolTip(
            "文本模型通常不到 1 秒；视觉模型冷启动可达数十秒\n"
            "（2026-10-11 实测硅基流动：Qwen3-VL-32B-Instruct 0.8s / "
            "Qwen3-VL-8B-Instruct 22s）。\n"
            "超时太短会让截图问答（Alt+S）间歇性失败，建议 ≥60。"
        )
        form.addRow("请求超时", self._timeout_spin)

        root.addLayout(form)

        # 探测结果输出区：等宽字体 + 只读 + 自带滚动条。
        # 用 QPlainTextEdit 而不是 QLabel —— 结果最多有 7 步，
        # QLabel 要么被布局拉伸成一大块空白，要么把长文本撑破版面。
        self._status = QPlainTextEdit()
        self._status.setObjectName("probeStatus")
        self._status.setReadOnly(True)
        self._status.setUndoRedoEnabled(False)
        self._status.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self._status.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._status.setFixedHeight(132)
        self._status.setProperty("role", "info")
        self._status.setFont(theme().font_mono)
        # 没有内容时整块收掉 —— 它固定高 132，空着就是一大片占位的灰框
        self._status.setVisible(False)
        root.addWidget(self._status)

    # ------------------------------------------------------------ 载入 / 回填

    @staticmethod
    def _match_preset(base_url: str) -> int:
        base = (base_url or "").rstrip("/")
        for i, p in enumerate(PROVIDERS):
            if p.base_url and p.base_url.rstrip("/") == base:
                return i
        return len(PROVIDERS) - 1        # 自定义

    def load_from_config(self) -> None:
        c = self._cfg
        base_url = c.get("ai.base_url", "") or ""
        self._preset_combo.setCurrentIndex(self._match_preset(base_url))
        self._base_url_edit.setText(base_url)

        preset = PROVIDERS[self._preset_combo.currentIndex()]
        self._fill_combo(self._model_combo, preset.models, c.get("ai.model", ""))
        self._fill_combo(self._vision_combo, preset.vision_models,
                         c.get("ai.vision_model", ""))

        ref = c.get("ai.api_key_ref", "") or ""
        self._keyring_mode = bool(ref.startswith(key_store.REF_PREFIX))
        # 密钥库里已有钥匙时，输入框**留空**：填不填都不代表里面有值，
        # 而把密钥回填进来会让「保存」不可避免地把它再写一遍配置（明文模式）。
        self._initial_key = "" if self._keyring_mode else (c.get("ai.api_key", "") or "")
        self._key_edit.setText(self._initial_key)
        self._timeout_spin.setValue(int(c.get("ai.request_timeout", 60) or 60))

        if self._keyring_mode:
            self._key_mode.set_index(0)
            masked = key_store.mask(key_store.load_key(ref))
            # 这条是**状态说明**不是提示：密钥存在哪、脱敏后长什么样、
            # 改动会发生什么，用户都需要知道
            self.set_status(
                f"当前密钥来自系统密钥库（{key_store.entry_of(ref)}，{masked}）。"
                "输入框留空表示不修改；填入新 Key 则会覆盖密钥库里的这一条。",
                "text_secondary")
        else:
            # 默认落在哪一档，取决于「现在有没有明文密钥」：
            #   有明文 → 停在明文档。**不**替他默默迁移 —— 保存一次别的设置
            #           就把密钥搬了家，用户下次找不到钥匙只会以为丢了。
            #           要搬就自己切过去（切的那一下会说清楚会发生什么）。
            #   没明文 → 默认密钥库（有就用，没有则退回明文档）。
            prefer_store = not str(c.get("ai.api_key", "") or "") and key_store.available()
            self._key_mode.set_index(0 if prefer_store else 1)
            # 明文模式**不设常驻提示** —— 用户 2026-10-14 明确要求去掉这类
            # 一直挂着的说明。需要说的（怎么搬进密钥库）放在切换时的状态里，
            # 以及「保存位置」控件的 tooltip 上：**在用户要动它的那一刻**出现。
            self.set_status("")

    @staticmethod
    def _fill_combo(combo: QComboBox, items: List[str], current: str,
                    prefer_candidates: bool = False) -> None:
        """填充可编辑下拉的候选。

        Args:
            prefer_candidates:
                False（载入配置）—— 原样保留配置里的值，即使不在候选里；
                因为用户可能用的是自己手填的模型名，不该被候选覆盖。
                True（切换服务商）—— 换了服务商，模型名必须跟着换：
                当前值在新候选里就保留，否则退到第一个候选（候选为空则清空）。
        """
        combo.clear()
        combo.addItems(items)
        if not prefer_candidates:
            combo.setCurrentText(current or "")
            return
        if current and current in items:
            combo.setCurrentText(current)
        elif items:
            combo.setCurrentIndex(0)
        else:
            combo.setCurrentText("")

    def _on_preset_changed(self, index: int) -> None:
        if self._loading:
            return
        preset = PROVIDERS[index]
        if preset.base_url:
            self._base_url_edit.setText(preset.base_url)
        # 换服务商 = 换模型命名体系（deepseek-chat vs Qwen/Qwen3-8B），
        # 所以候选要**替换**而不是合并：当前值不在新候选里就换掉。
        self._fill_combo(self._model_combo, preset.models,
                         self._model_combo.currentText(), prefer_candidates=True)
        self._fill_combo(self._vision_combo, preset.vision_models,
                         self._vision_combo.currentText(), prefer_candidates=True)
        if preset.note:
            self.set_status(preset.note, "text_secondary")

    # ------------------------------------------------------------ 取值 / 校验

    def _on_key_mode_changed(self, index: int) -> None:
        """切保存位置时把「现在这把钥匙会怎样」说清楚，别等保存完才发现。"""
        if self._loading:
            return
        if index == 0:
            if not key_store.available():
                self.set_status("本机没有可用的系统密钥库，无法选择该项。", "error")
                return
            has_plain = bool(str(self._cfg.get("ai.api_key", "") or ""))
            ref = str(self._cfg.get("ai.api_key_ref", "") or "")
            if has_plain and not ref.startswith(key_store.REF_PREFIX):
                self.set_status(
                    "保存时会把这把明文密钥搬进系统密钥库，"
                    "并清除配置文件里的明文。", "text_secondary")
            else:
                self.set_status(
                    "保存时会写入系统密钥库，配置里只留一个引用。", "text_secondary")
            return
        self.set_status(
            "保存时密钥将明文写进配置文件（会随备份与「导出全部数据」被带走）。",
            "text_secondary")

    def collect(self) -> dict:
        """收集表单值。`api_key` 是**解析后**的密钥（用于测试连接）：

        密钥库模式下输入框留空表示「不修改」，此时测试连接要用密钥库里
        现有的那把 —— 直接拿空串去测会得到一个「没配 Key」的假失败。
        """
        typed = self._key_edit.text().strip()
        return {
            "base_url": self._base_url_edit.text().strip(),
            "model": self._model_combo.currentText().strip(),
            "vision_model": self._vision_combo.currentText().strip(),
            "api_key": self._resolved_key(typed),
            "api_key_typed": typed,
            "key_mode": self._key_mode.index(),
            "timeout": self._timeout_spin.value(),
            "api_key_changed": typed != self._initial_key,
        }

    def _resolved_key(self, typed: str) -> str:
        """输入框里填了新值就用新的；没填就沿用它背后那一把。

        密钥库模式 → 读密钥库；明文模式 → 读配置里的旧值。
        """
        if typed:
            return typed
        if self._keyring_mode or self._key_mode.index() == 0:
            return key_store.load_key(self._cfg.get("ai.api_key_ref", ""))
        return str(self._cfg.get("ai.api_key", "") or "")

    def validate(self) -> tuple[bool, str, str]:
        """返回 `(ok, 标题, 说明)`。"""
        vals = self.collect()
        if not vals["base_url"]:
            return False, "配置不完整", "接口地址不能为空。"
        if not vals["model"]:
            return False, "配置不完整", "文本模型不能为空。"
        if vals["key_mode"] == 0:
            if not key_store.available():
                return False, "无法保存", "本机没有可用的系统密钥库，请改用明文保存。"
            entry = key_store.entry_for_base_url(vals["base_url"])
            if vals["api_key_changed"] and not vals["api_key_typed"]:
                return False, "密钥为空", (
                    f"要存入系统密钥库，请填写密钥"
                    f"（条目名将是 {entry}）；留空表示不修改。")
            if not vals["api_key_changed"] and not vals["api_key"]:
                return False, "还没有密钥", (
                    "当前没有已保存的密钥可迁移，请先填写一把。")
        return True, "", ""

    def is_testing(self) -> bool:
        return self._testing

    # ------------------------------------------------------------ 测试连接

    def test(self) -> None:
        if self._testing:
            return
        vals = self.collect()
        if not vals["base_url"]:
            self.set_status("请先填写接口地址。", "error")
            return

        self._testing = True
        self.busy_changed.emit(True)
        self.set_status("正在测试…（发起真实网络请求）", "text_secondary")

        if not self._probe_connected:
            _BRIDGE.done.connect(self._on_probe_done)
            self._probe_connected = True

        # 丢进子线程 —— 主线程绝不等网络
        _POOL.submit(self._run_probe, vals)

    @staticmethod
    def _run_probe(vals: dict) -> None:
        try:
            res = probe_api(
                base_url=vals["base_url"],
                api_key=vals["api_key"],
                model=vals["model"],
                vision_model=vals["vision_model"],
                timeout=min(vals["timeout"], 20),
            )
        except Exception as e:  # noqa: BLE001 —— 探测层兜底，绝不炸到 UI
            res = ProbeResult(False, f"{type(e).__name__}: {e}")
        # 信号在子线程 emit，Qt 自动排队回主线程
        _BRIDGE.done.emit(res)

    def _on_probe_done(self, res: ProbeResult) -> None:
        self._testing = False
        self.busy_changed.emit(False)

        lines = []
        for name, ok, detail in res.steps:
            mark = "✓" if ok else "✗"
            lines.append(f"{mark} {name}" + (f" — {detail}" if detail else ""))
        body = "\n".join(lines) or res.summary

        if res.ok:
            self.set_status(f"{res.summary}\n{body}", "success")
            if res.models:
                self._apply_models(res.models)
        else:
            self.set_status(f"连接失败 —— {res.failed_step or res.summary}\n{body}", "error")

    def _apply_models(self, ids: List[str]) -> None:
        """把 /models 返回的真实模型列表灌进两个下拉的候选。"""
        from engine.ai.probe import suggest_models

        cur_model = self._model_combo.currentText()
        cur_vision = self._vision_combo.currentText()
        self._fill_combo(self._model_combo, suggest_models(ids, "文本", limit=40), cur_model)
        self._fill_combo(self._vision_combo, suggest_models(ids, "视觉", limit=40), cur_vision)

    # ------------------------------------------------------------ 保存

    def save(self) -> bool:
        """写回配置。校验不通过时返回 False（调用方负责弹提示）。

        密钥的三种走向（按「保存位置 × 用户改没改」分开，不许合流）：
            密钥库 + 填了新值   → 写密钥库，配置里只留引用（**明文一律清空**）
            密钥库 + 没改内容   → 密钥库原样不动；若原来是明文，顺手迁进去
            明文   + 填了新值   → 写明文，并清掉引用（否则会优先读到密钥库，
                                   用户以为改了却没生效 —— 这个坑踩过）
            明文   + 没改内容   → 什么都不动
        """
        ok, title, message = self.validate()
        if not ok:
            self.set_status(f"{title}：{message}", "error")
            return False
        vals = self.collect()
        c = self._cfg
        c.set("ai.provider", "openai_compat")
        c.set("ai.base_url", vals["base_url"])
        c.set("ai.model", vals["model"])
        c.set("ai.vision_model", vals["vision_model"])
        c.set("ai.request_timeout", vals["timeout"])

        entry = key_store.entry_for_base_url(vals["base_url"])
        if vals["key_mode"] == 0:
            if vals["api_key_changed"]:
                stored, why = key_store.store_key(entry, vals["api_key_typed"])
                if not stored:
                    self.set_status(f"保存失败：{why}", "error")
                    return False
            elif not str(c.get("ai.api_key_ref", "") or "").startswith(
                    key_store.REF_PREFIX):
                # 从明文迁到密钥库（用户没动内容，只是换了保存方式）
                stored, why = key_store.store_key(entry, vals["api_key"])
                if not stored:
                    self.set_status(f"迁移失败：{why}", "error")
                    return False
            # 引用与明文**必须一起改**：留着旧明文，导出的配置里就还有一份钥匙
            c.set("ai.api_key", "")
            c.set("ai.api_key_ref", key_store.ref_for(entry))
            self._keyring_mode = True
        elif vals["api_key_changed"]:
            c.set("ai.api_key", vals["api_key_typed"])
            c.set("ai.api_key_ref", "")
            self._keyring_mode = False

        c.save()

        # 保存后「初始值」是解析后的钥匙，但输入框仍保持留空/原样 ——
        # 下次 collect() 才能正确判断「用户改没改」。
        self._initial_key = "" if self._keyring_mode else vals["api_key_typed"]
        log_manager.info(
            f"AI 配置已更新: {vals['base_url']} / {vals['model']}"
            f" / vision={vals['vision_model'] or '（未配置）'}"
            f" / 密钥位置={'系统密钥库' if self._keyring_mode else '配置文件'}"
            f" / 条目={entry if self._keyring_mode else '—'}"
        )
        self.applied.emit()
        return True

    # ------------------------------------------------------------ 状态区

    #: 旧调用方传的是**颜色 token 名**（success / error / text_secondary），
    #: 这里映射成语义 role —— 颜色由全局 QSS 决定，本文件不再拼任何颜色字符串。
    _ROLE_ALIAS = {
        "text_secondary": "info",
        "success": "ok",
        "error": "error",
        "warning": "warn",
    }

    def set_status(self, text: str, role: str = "info") -> None:
        """更新输出区内容与语义角色（info / ok / warn / error）。

        文本为空时整块隐藏：这个区是**输出区**，只在真有结果 / 真出错时
        才该出现。常驻一句「填好后点测试连接」既占版面又没人看。
        """
        self._status.setPlainText(text)
        self._status.setProperty("role", self._ROLE_ALIAS.get(role, role))
        # 动态属性变了必须重新 polish，否则 QSS 的 [role="..."] 选择器不生效
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
        self._status.setVisible(bool(text.strip()))

    def refresh_theme(self) -> None:
        self._status.setFont(theme().font_mono)

    # ------------------------------------------------------------ 杂项

    def _on_toggle_key(self, shown: bool) -> None:
        self._key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        )
        self._btn_show_key.set_icon("eye-off" if shown else "eye")

    def detach_probe(self) -> None:
        """断开探测信号。可重入 —— `finished` 与 `closeEvent` 都会走到这里。

        用标志位而不是只 try/except：PySide6 在重复 disconnect 时**不抛异常**，
        而是发一条 `RuntimeWarning` 到 stderr。打包后的 exe 没有控制台，
        这条警告会静默积累；更重要的是它意味着代码在猜信号状态。
        """
        if not self._probe_connected:
            return
        self._probe_connected = False
        try:
            _BRIDGE.done.disconnect(self._on_probe_done)
        except (TypeError, RuntimeError):
            pass

    def has_unsaved_changes(self) -> bool:
        c = self._cfg
        vals = self.collect()
        return (
            vals["base_url"] != (c.get("ai.base_url", "") or "")
            or vals["model"] != (c.get("ai.model", "") or "")
            or vals["vision_model"] != (c.get("ai.vision_model", "") or "")
            or vals["timeout"] != int(c.get("ai.request_timeout", 60) or 60)
            # 只切了保存位置也算改动 —— 否则「搬到密钥库」这一步永远判不出未保存
            or (vals["key_mode"] == 0) != bool(self._keyring_mode)
            or vals["api_key_changed"]
        )
