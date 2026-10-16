#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""API — 真实模型服务连通性自检（需要真实 API Key，**不进自动回归**）。

为什么单独一个脚本
    其余 spike / M1 / M2 全部用假 Provider，不碰网络，可以无限次重跑。
    但「配置对不对」只有真实请求能回答：base_url 拼错、模型名少了命名空间
    前缀、Key 没生效、余额不足 —— 这些都会在第一个人工实测时才暴露。
    本脚本把这一步也变成一键可复现的。

用法
    cd "C:/Users/LL/Desktop/处理沙盒/petgame_demo"

    python dev_bootstrap.py spikes/api_check.py
    python dev_bootstrap.py spikes/api_check.py --model deepseek-ai/DeepSeek-V3
    python dev_bootstrap.py spikes/api_check.py --skip-vision
    python dev_bootstrap.py spikes/api_check.py --text "用一句话解释量子纠缠"

测什么
    1. 配置完整性：base_url / model / api_key 是否齐备
    2. 连通性：GET {base_url}/models（同时验证地址与鉴权）
    3. 文本链路：是否**真的流式**（TTFB / 块数 / 总时长 / 字符数）
    4. 翻译链路：translate 预设能否产出译文
    5. 视觉链路：视觉模型能否认出合成测试图（红圆 + 数字 42）

判定
    - 文本链路：拿到非空回答，且分块数 > 1（证明是真流式，不是一次性返回）
    - 视觉链路：拿到非空回答（若同时提到 42 或 红，标记为强通过）
"""
from __future__ import annotations

import argparse
import base64
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import Report, bootstrap  # noqa: E402

bootstrap()

import requests  # noqa: E402

from engine.ai import build_messages, get_preset, resolve_api_key  # noqa: E402
from engine.ai.probe import list_models, suggest_models  # noqa: E402
from engine.ai.provider import build_user_content  # noqa: E402
from engine.ai.providers.openai_compat import OpenAICompatProvider  # noqa: E402
from engine.ai.types import ChatMessage, ProviderError  # noqa: E402

# ---------------------------------------------------------------- 配置


def load_config():
    """读取生效配置（默认配置 + 用户配置合并后的结果）。"""
    from data.config_manager import config_manager

    return config_manager


def mask(key: str) -> str:
    """脱敏口径与产品内一致（见 `data/key_store.py`）——
    自检脚本不许有自己的一套，否则「日志里泄露长度」会从脚本这条路过关。"""
    from data.key_store import mask as _mask

    return _mask(key)


# ---------------------------------------------------------------- 测试图


def make_test_image_data_url() -> str:
    """合成一张测试图：白底 + 红色圆 + 黑色数字 42。

    为什么不用截屏
        截屏内容随环境变化，无法断言；合成图的期望答案是确定的，
        这样「视觉链路是否真的工作」才有客观判据。
        顺带复用了产品自己的 `CaptureService.to_data_url`。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication

    from native.capture import CaptureService

    app = QApplication.instance() or QApplication([])  # noqa: F841

    pm = QPixmap(320, 200)
    pm.fill(QColor("white"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(220, 30, 30))
    p.drawEllipse(30, 30, 120, 120)          # 红色圆
    p.setPen(QColor(10, 10, 10))
    p.setFont(QFont("Arial", 40, QFont.Bold))
    p.drawText(190, 120, "42")               # 数字 42
    p.end()

    return CaptureService().to_data_url(pm)


# ---------------------------------------------------------------- 请求


def probe_models(provider: OpenAICompatProvider) -> tuple[bool, str, list[str]]:
    """GET /models —— 验证地址与鉴权，并列出可用模型。

    复用 `engine.ai.probe.list_models`（UI 的「测试连接」走的是同一个函数），
    避免这里和设置对话框各写一套、结果不一致。
    """
    return list_models(provider.base_url, provider.api_key, timeout=20)


def _suggest(rep: Report, ids: list[str], wanted: str, kind: str = "文本") -> None:
    """把候选模型打印到报告里（复用 `engine.ai.probe.suggest_models`）。

    聚合平台的模型名带命名空间前缀（`Qwen/Qwen3-VL-8B-Instruct`），
    少一个斜杠前缀就 404 —— 报错信息往往不直观。这里直接把候选列出来。
    """
    cands = suggest_models(ids, kind, limit=10)
    if not cands:
        rep.note(f"未能从 /models 里推断出{kind}模型候选，请到服务商控制台查看。")
        return
    rep.note(f"建议的{kind}模型候选（共 {len(cands)} 个，取前 10）：")
    for c in cands:
        rep.note(f"    {c}")


def stream_once(provider: OpenAICompatProvider, messages, model: str,
                timeout_note: str = "") -> dict:
    """跑一次流式请求，返回计时与内容统计。异常经 ProviderError 抛出。"""
    t0 = time.perf_counter()
    ttfb = None
    chunks: list[str] = []
    for delta in provider.stream(messages, model):
        if ttfb is None:
            ttfb = (time.perf_counter() - t0) * 1000
        chunks.append(delta)
    total = (time.perf_counter() - t0) * 1000
    text = "".join(chunks)
    return {
        "ttfb_ms": round(ttfb, 1) if ttfb is not None else None,
        "total_ms": round(total, 1),
        "chunks": len(chunks),
        "chars": len(text),
        "text": text,
        "model": model,
        "note": timeout_note,
    }


# ---------------------------------------------------------------- 主流程


def main() -> int:
    ap = argparse.ArgumentParser(description="真实模型服务连通性自检")
    ap.add_argument("--model", default="", help="覆盖文本模型")
    ap.add_argument("--vision-model", default="", help="覆盖视觉模型")
    ap.add_argument("--text", default="", help="自定义测试文本")
    ap.add_argument("--skip-vision", action="store_true", help="跳过视觉链路")
    ap.add_argument("--skip-translate", action="store_true", help="跳过翻译链路")
    args = ap.parse_args()

    cfg = load_config()
    base_url = cfg.get("ai.base_url", "")
    model = args.model or cfg.get("ai.model", "")
    vision_model = args.vision_model or cfg.get("ai.vision_model", "") or ""
    api_key = resolve_api_key(cfg)
    timeout = int(cfg.get("ai.request_timeout", 60) or 60)

    rep = Report(
        "API",
        "真实模型服务连通性自检",
        "填好 base_url / model / api_key 后，问答 / 翻译 / 截图三条链路都能拿到真实回答",
        "文本链路有流式增量；视觉模型能识别合成测试图",
    )

    rep.metric("base_url", base_url or "(空)")
    rep.metric("model", model or "(空)")
    rep.metric("vision_model", vision_model or "(未配置，截图将回退主模型)")
    rep.metric("api_key", mask(api_key))
    rep.metric("request_timeout", timeout, " s")

    if not base_url or not model:
        rep.check("配置完整（base_url + model）", False,
                  "请编辑 ~/.pet_demo/user_config.json 的 ai 节")
        rep.finish("ERROR")
        return 2

    if not api_key:
        rep.check("已配置 api_key", False,
                  "方式一：控制中心 →「AI 服务」把密钥存进系统密钥库（推荐）；"
                  "方式二：ai.api_key 直接填明文；"
                  "方式三：keyring set pet_demo_ai <名> 并把 ai.api_key_ref 设为 keyring:<名>")
        rep.finish("ERROR")
        return 2
    rep.check("已配置 api_key", True)

    provider = OpenAICompatProvider(base_url=base_url, api_key=api_key, timeout=timeout)

    # ---------- 1. 连通性 / 鉴权 ----------
    ok, detail, ids = probe_models(provider)
    rep.check("GET /models 连通（地址与鉴权正确）", ok, detail)
    if ok and ids:
        rep.metric("可用模型数", len(ids))
        for mid in ids[:8]:
            rep.note(f"可用模型示例: {mid}")
        if model not in ids:
            rep.check(f"配置的 model 在可用列表中（{model}）", None,
                      "未在 /models 返回列表里找到 —— 可能是命名空间前缀写错，"
                      "也可能只是分页/别名问题，请人工核对")
            _suggest(rep, ids, model, kind="文本")
        else:
            rep.check(f"配置的 model 在可用列表中（{model}）", True)
        if vision_model and vision_model not in ids:
            rep.check(f"视觉模型在可用列表中（{vision_model}）", None,
                      "未找到，请从下面建议里挑一个填到 ai.vision_model")
            _suggest(rep, ids, vision_model, kind="视觉")
        elif vision_model:
            rep.check(f"视觉模型在可用列表中（{vision_model}）", True)
        elif not args.skip_vision:
            _suggest(rep, ids, "", kind="视觉")

    if not ok:
        rep.note("连通性失败，后续链路测试跳过。")
        rep.finish("FAIL")
        return 1

    # ---------- 2. 文本链路 ----------
    text = args.text or "用一句话解释什么是递归。"
    preset = get_preset("ask")
    msgs = build_messages(preset, text)
    rep.note(f"文本测试输入: {text}")

    try:
        r = stream_once(provider, msgs, model)
    except ProviderError as e:
        rep.check("文本链路：请求成功", False, str(e))
        rep.finish("FAIL")
        return 1

    rep.metric("文本·首字节 (TTFB)", r["ttfb_ms"], " ms")
    rep.metric("文本·总耗时", r["total_ms"], " ms")
    rep.metric("文本·流式块数", r["chunks"])
    rep.metric("文本·回答字数", r["chars"])
    rep.note("回答预览: " + r["text"][:160].replace("\n", " "))
    rep.check("文本链路：拿到非空回答", r["chars"] > 0)
    rep.check("文本链路：是真流式（块数 > 1）", r["chunks"] > 1,
              f"块数={r['chunks']}（=1 说明网关忽略了 stream 参数）")

    # ---------- 3. 翻译链路 ----------
    if not args.skip_translate:
        src = "The quick brown fox jumps over the lazy dog."
        tr = get_preset("translate")
        tmsgs = build_messages(tr, src, language="zh")
        try:
            rt = stream_once(provider, tmsgs, model)
            rep.metric("翻译·总耗时", rt["total_ms"], " ms")
            rep.metric("翻译·译文", rt["text"][:80].replace("\n", " "))
            rep.check("翻译链路：拿到非空译文", rt["chars"] > 0)
            rep.check("翻译链路：译文非原文照抄", rt["text"].strip() != src)
        except ProviderError as e:
            rep.check("翻译链路：请求成功", False, str(e))

    # ---------- 4. 视觉链路 ----------
    if args.skip_vision:
        rep.note("按参数要求跳过视觉链路。")
    elif not vision_model:
        rep.check("视觉链路：已配置 vision_model", False,
                  "未配置 —— Alt+S 截图问答会把图片发给纯文本模型，通常直接报错。"
                  "请设置 ai.vision_model（如 Qwen/Qwen3-VL-8B-Instruct）")
    else:
        try:
            data_url = make_test_image_data_url()
        except Exception as e:  # noqa: BLE001
            rep.check("视觉链路：合成测试图", False, f"{type(e).__name__}: {e}")
        else:
            rep.metric("测试图大小 (base64)", len(data_url), " 字符")
            vmsgs = [
                ChatMessage("system", "你是一个图像识别助手，只回答看到的内容。"),
                ChatMessage("user", build_user_content(
                    "这张图里有什么形状？什么颜色？写了什么数字？简短回答。",
                    data_url,
                )),
            ]
            try:
                rv = stream_once(provider, vmsgs, vision_model)
                rep.metric("视觉·总耗时", rv["total_ms"], " ms")
                rep.metric("视觉·回答字数", rv["chars"])
                rep.note("视觉回答: " + rv["text"][:160].replace("\n", " "))
                rep.check("视觉链路：拿到非空回答", rv["chars"] > 0)
                hit = ("42" in rv["text"]) or ("红" in rv["text"])
                # detail 无论成败都会打印，所以这里必须按结果给不同文案，
                # 否则成功时也会显示「未命中关键词」这种自相矛盾的提示。
                rep.check(
                    "视觉链路：识别出图中内容（42 / 红色圆）",
                    hit,
                    "命中关键词 42 / 红" if hit else "未命中关键词，可能模型看错了 —— 请人工查看上面的回答",
                )
            except ProviderError as e:
                rep.check("视觉链路：请求成功", False, str(e))

    # ---------- 汇总 ----------
    failed = [c for c in rep.checks if c["ok"] is False]
    verdict = "PASS" if not failed else "FAIL"
    rep.finish(verdict)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
