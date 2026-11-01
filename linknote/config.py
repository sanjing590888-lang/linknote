"""配置读取：.env（若存在）+ 环境变量。所有可调项都在这里，别在业务代码里写死。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """极简 .env 解析：KEY=VALUE，忽略注释与空行。不覆盖已存在的环境变量。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Config:
    output_dir: Path = Path("./linknote-notes")
    keep_media: bool = False

    asr_provider: str = "none"
    asr_base_url: str = ""
    asr_model: str = ""
    asr_api_key: str = ""

    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""

    http_timeout: int = 30
    retries: int = 2
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
    mobile_user_agent: str = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    )

    douyin_headless: bool = True
    douyin_cdp_url: str = ""

    # 输出风格：plain（任何 Markdown 编辑器都能看）/ obsidian（用 callout 等语法）
    dialect: str = "plain"
    frontmatter: bool = True

    extra: dict = field(default_factory=dict)

    @property
    def asr_enabled(self) -> bool:
        return bool(self.asr_base_url and self.asr_model and self.asr_api_key)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_model and self.llm_api_key)

    def redacted(self) -> dict:
        """给 doctor / 日志用的脱敏视图。"""
        def mask(v: str) -> str:
            if not v:
                return "(未配置)"
            return v[:4] + "****" + v[-2:] if len(v) > 8 else "****"

        return {
            "output_dir": str(self.output_dir),
            "keep_media": self.keep_media,
            "asr": {
                "provider": self.asr_provider,
                "base_url": self.asr_base_url or "(未配置)",
                "model": self.asr_model or "(未配置)",
                "api_key": mask(self.asr_api_key),
            },
            "llm": {
                "base_url": self.llm_base_url or "(未配置)",
                "model": self.llm_model or "(未配置)",
                "api_key": mask(self.llm_api_key),
            },
            "http_timeout": self.http_timeout,
            "retries": self.retries,
            "douyin_headless": self.douyin_headless,
            "douyin_cdp_url": self.douyin_cdp_url or "(未配置)",
            "dialect": self.dialect,
            "frontmatter": self.frontmatter,
        }


def load_config(env_file: Path | str | None = None) -> Config:
    if env_file:
        _load_dotenv(Path(env_file))
    # 默认读项目根目录的 .env（若调用方没指定）
    _load_dotenv(Path.cwd() / ".env")

    return Config(
        output_dir=Path(os.environ.get("LINKNOTE_OUTPUT", "./linknote-notes")).expanduser(),
        keep_media=_bool("LINKNOTE_KEEP_MEDIA", False),
        asr_provider=os.environ.get("LINKNOTE_ASR_PROVIDER", "none"),
        asr_base_url=os.environ.get("LINKNOTE_ASR_BASE_URL", ""),
        asr_model=os.environ.get("LINKNOTE_ASR_MODEL", ""),
        asr_api_key=os.environ.get("LINKNOTE_ASR_API_KEY", ""),
        llm_base_url=os.environ.get("LINKNOTE_LLM_BASE_URL", ""),
        llm_model=os.environ.get("LINKNOTE_LLM_MODEL", ""),
        llm_api_key=os.environ.get("LINKNOTE_LLM_API_KEY", ""),
        http_timeout=_int("LINKNOTE_HTTP_TIMEOUT", 30),
        retries=_int("LINKNOTE_RETRIES", 2),
        dialect=os.environ.get("LINKNOTE_DIALECT", "plain").strip().lower() or "plain",
        frontmatter=_bool("LINKNOTE_FRONTMATTER", True),
        douyin_headless=_bool("LINKNOTE_DOUYIN_HEADLESS", True),
        douyin_cdp_url=os.environ.get("LINKNOTE_DOUYIN_CDP_URL", ""),
    )
