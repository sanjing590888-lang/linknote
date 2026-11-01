"""数据模型：适配器产出 Content，笔记生成只依赖它。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    COMPLETE = "complete"      # 内容与笔记都齐
    PARTIAL = "partial"        # 拿到了内容，但缺口播/缺图/未核验
    FAILED = "failed"          # 关键内容没拿到


class Source(str, Enum):
    NATIVE_TEXT = "native_text"   # 平台原生正文（公众号）
    SUBTITLE = "subtitle"         # 平台字幕
    ASR = "asr"                   # 音频转写
    NONE = "none"                 # 只有元信息，没有正文


@dataclass
class Content:
    platform: str
    content_id: str
    title: str
    author: str
    url_raw: str
    url_resolved: str

    published_at: str | None = None
    fetched_at: str = ""

    source: Source = Source.NONE
    text: str = ""
    text_note: str = ""            # 关于这段文本怎么来的（原文 / ASR，可能不准确）
    stats: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)

    media_path: str | None = None          # 原视频/原始媒体（保留时才写）
    audio_removed: bool = False
    attachment_dir: str | None = None

    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def has_text(self) -> bool:
        return len(self.text.strip()) >= 20

    @property
    def status(self) -> Status:
        if self.has_text:
            return Status.PARTIAL if (self.warnings or self.errors) else Status.COMPLETE
        return Status.FAILED
