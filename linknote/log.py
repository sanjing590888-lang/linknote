"""日志：控制台 + <output>/.linknote/runs/run-<ts>.log，写入前统一脱敏。"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

_SECRET_PATTERNS = [
    (re.compile(r"(sk-[\w\-]{6})[\w\-]+"), r"\1***"),
    (re.compile(r"(Bearer\s+)[\w\-._]{8,}"), r"\1***"),
    (re.compile(r"(?i)(api[_-]?key|app[_-]?secret|token|cookie|authorization)\s*[=:]\s*\S+"),
     r"\1=***"),
    (re.compile(r"(?i)([?&](?:key|token|secret)=)[\w\-]+"), r"\1***"),
]


def redact(text: str) -> str:
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging(log_dir: Path, verbose: bool = False) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("linknote")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    logger.propagate = False

    fmt = RedactingFormatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    fh = logging.FileHandler(
        log_dir / f"run-{time.strftime('%Y%m%d-%H%M%S')}.log", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger
