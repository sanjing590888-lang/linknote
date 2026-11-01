"""音频转写适配器：兼容 OpenAI /audio/transcriptions 形态的服务。

第一版实测可用：硅基流动 FunAudioLLM/SenseVoiceSmall（免费）。
其他服务只要满足下面的约定即可复用，未验证的服务不写进 README。
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import requests

from .config import Config
from .errors import TranscribeFailure, TranscribeNotConfigured


def extract_audio(media_path: Path, workdir: Path) -> Path:
    """ffmpeg 抽音轨：16k 单声道 32kbps，几十 MB 视频 → 几百 KB 音频。"""
    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / (media_path.stem + ".m4a")
    cmd = [
        "ffmpeg", "-v", "error", "-y", "-i", str(media_path),
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", str(out),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except FileNotFoundError as exc:
        raise TranscribeFailure(
            "没有找到 ffmpeg，无法抽取音轨",
            hint="macOS: brew install ffmpeg / Ubuntu: apt install ffmpeg",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise TranscribeFailure("ffmpeg 抽音轨超时（视频可能过长）") from exc
    if proc.returncode != 0 or not out.is_file():
        raise TranscribeFailure(f"ffmpeg 抽音轨失败：{proc.stderr.strip()[:300]}")
    return out


def clean_transcript(text: str) -> str:
    """清洗 ASR 输出：去掉模型自带的标记与表情（SenseVoice 会插 🎼 之类）。"""
    text = re.sub(r"<\|[^|]*\|>", "", text)
    text = re.sub(r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U0000FE0F]", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def transcribe(audio_path: Path, cfg: Config, *, logger=None) -> str:
    """返回转写文本。失败抛 TranscribeFailure，未配置抛 TranscribeNotConfigured。"""
    if not cfg.asr_enabled:
        raise TranscribeNotConfigured(
            "没有配置转写服务，无法获得口播内容",
            hint="在 .env 里填 LINKNOTE_ASR_BASE_URL / MODEL / API_KEY，或用 --extract-only 只取元信息",
        )

    url = cfg.asr_base_url.rstrip("/") + "/audio/transcriptions"
    last_error = ""
    for attempt in range(cfg.retries + 1):
        try:
            with audio_path.open("rb") as fh:
                resp = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {cfg.asr_api_key}"},
                    files={"file": (audio_path.name, fh, "audio/mp4")},
                    data={"model": cfg.asr_model},
                    timeout=max(cfg.http_timeout, 120),
                )
            if resp.status_code == 200:
                data = resp.json()
                text = (data.get("text") or "").strip()
                if not text:
                    raise TranscribeFailure("转写服务返回空文本")
                return text
            if resp.status_code in (401, 403):
                raise TranscribeFailure(
                    f"转写服务拒绝了密钥（HTTP {resp.status_code}）",
                    hint="检查 LINKNOTE_ASR_API_KEY 是否有效",
                )
            if resp.status_code == 429:
                last_error = "限流（HTTP 429）"
                time.sleep(min(2 ** attempt * 3, 20))
                continue
            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            if resp.status_code >= 500:
                time.sleep(min(2 ** attempt * 2, 10))
                continue
            break
        except requests.RequestException as exc:
            last_error = f"网络错误：{exc}"
            time.sleep(min(2 ** attempt * 2, 10))
    raise TranscribeFailure(f"转写失败：{last_error}")
