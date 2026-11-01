"""摘要与关键观点。

两种模式，笔记里会明确标出用的是哪一种：
- extractive（默认，不需要任何密钥）：抽取式算法挑句子，属于**机械抽取，不是模型生成**
- llm（配置了 LINKNOTE_LLM_* 才启用）：调用 OpenAI 兼容的 chat completions

无论哪种模式，都不做外部事实核查；原文里的数字与结论照抄并标注来源。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import requests

from .config import Config

STOPWORDS = set("的了是我你他她它我们你们他们这那就和也很都而在有个不没要有会着过把被"
                "如果说可以但是这个那个什么怎么为什么因为所以但是然后而且以及对于通过".split())


@dataclass
class Digest:
    mode: str                          # extractive | llm
    summary: list[str] = field(default_factory=list)
    keypoints: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    model: str = ""
    warnings: list[str] = field(default_factory=list)
    fallback: bool = False             # 配了模型但调用失败、退回抽取式
    fallback_reason: str = ""


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text)
    parts = re.split(r"(?<=[。！？!?；;\n])", text)
    out = []
    for p in parts:
        p = p.strip(" \n")
        p = re.sub(r"^[\d]+[.、)]\s*", "", p)      # 去掉 "1. " 这类序号
        p = re.sub(r"^[·•\-*]\s*", "", p)
        if len(p) >= 12 and p not in out:
            out.append(p)
    return out


def _score(sent: str) -> float:
    words = re.findall(r"[\u4e00-\u9fa5]{2}|[A-Za-z]{3,}|\d+(?:\.\d+)?%?", sent)
    if not words:
        return 0.0
    content = [w for w in words if w not in STOPWORDS]
    base = len(content) / (len(sent) ** 0.5 + 1)
    bonus = 0.35 if re.search(r"\d", sent) else 0.0         # 带数字的句子更可能是结论
    return base + bonus


def extractive(text: str, *, max_summary: int = 4, max_points: int = 5) -> Digest:
    sents = _sentences(text)
    if not sents:
        return Digest(mode="extractive")
    ranked = sorted(range(len(sents)), key=lambda i: _score(sents[i]), reverse=True)
    pick_sum = sorted(ranked[:max_summary])
    remaining = [i for i in ranked if i not in pick_sum][:max_points]
    pick_pts = sorted(remaining) if remaining else sorted(ranked[:max_points])
    return Digest(
        mode="extractive",
        summary=[sents[i] for i in pick_sum],
        keypoints=[sents[i] for i in pick_pts],
        actions=[],
        warnings=["未配置摘要模型，摘要与关键观点为抽取式算法（机械抽取），不是模型生成"],
    )


PROMPT = """你在为一份个人知识库整理笔记。只依据下面的内容，不要补充外部知识，不要做事实核查。
严格输出 JSON：{{"summary": ["最多3句"], "keypoints": ["3-6条关键观点，每条一句话"],
"actions": ["0-3条读者可执行的建议；内容里没有依据就给空数组"]}}
要求：
- 用中文，句子短，不要形容词堆砌。
- 数字、人名、产品名照原文写。
- 原文是语音转写时可能有错别字，遇到明显听错的词用方括号标注，例如 [Codex]。
- 不要写"本文介绍了""作者认为"这类空话。

内容：
{body}
"""


def llm_digest(text: str, cfg: Config) -> Digest:
    if not cfg.llm_enabled:
        raise RuntimeError("llm not configured")
    body = text[:12000]
    payload = {
        "model": cfg.llm_model,
        "messages": [
            {"role": "system", "content": "你是一个只依据给定材料做整理的笔记助手。"},
            {"role": "user", "content": PROMPT.format(body=body)},
        ],
        "temperature": 0.2,
    }
    resp = requests.post(
        cfg.llm_base_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {cfg.llm_api_key}",
                 "Content-Type": "application/json"},
        json=payload,
        timeout=max(cfg.http_timeout, 90),
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        raise ValueError("模型没有返回 JSON")
    data = json.loads(match.group(0))
    return Digest(
        mode="llm",
        model=cfg.llm_model,
        summary=[str(x) for x in data.get("summary", [])][:3],
        keypoints=[str(x) for x in data.get("keypoints", [])][:6],
        actions=[str(x) for x in data.get("actions", [])][:3],
    )


def digest(text: str, cfg: Config, *, logger=None) -> Digest:
    """优先模型；失败或未配置时回落到抽取式，并把原因写进 warnings。"""
    if cfg.llm_enabled:
        try:
            return llm_digest(text, cfg)
        except Exception as exc:                       # 不因为模型挂了就整单失败
            warn = f"摘要模型调用失败，已回落到抽取式：{exc}"
            if logger:
                logger.warning(warn)
            d = extractive(text)
            # 「未配置摘要模型」这句在回落场景是错的：模型配了，只是失败了
            d.warnings = [w for w in d.warnings if "未配置摘要模型" not in w]
            d.warnings.insert(0, warn)
            d.fallback = True
            d.fallback_reason = str(exc)
            return d
    return extractive(text)
