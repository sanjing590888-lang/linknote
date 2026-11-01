"""输出目录与任务状态。

目录布局（全部在用户 --output 指定的目录里，不绑定任何人的个人路径）：

    <output>/
      notes/2026-11-01_douyin_770280708137_标题.md
      raw/7702xxxx_content.txt          # 原文或 ASR 转写原文（独立存放）
      attachments/7702xxxx/img_01.jpg
      media/7702xxxx.mp4                # keep_media=true 时才有
      .linknote/state.json              # 去重与状态：requirements（要什么）+ done（做到了什么）
      .linknote/cache/<key>.json        # 正文与摘要缓存，补做时复用，不重复计费
      .linknote/runs/20261101-201500.log

重复执行规则：
- 上次 complete + 本次所需能力（含 keep_media）都做到 + 产物文件都在 + 笔记没被用户改过 → 跳过
- failed / partial、能力变了、产物被删 → 重跑，只补缺的那一步；已成功的转写 / 摘要直接复用（摘要要求正文哈希一致）
- --force → 不看缓存，全部重做；旧笔记备份 .md.bak，手改过的笔记另存 .rerun-<ts>.md
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .errors import OutputNotWritable
from .models import Content

STATE_DIR = ".linknote"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.notes_dir = self.root / "notes"
        self.raw_dir = self.root / "raw"
        self.attachments_dir = self.root / "attachments"
        self.media_dir = self.root / "media"
        self.state_dir = self.root / STATE_DIR
        self.state_file = self.state_dir / "state.json"
        self.cache_dir = self.state_dir / "cache"

    # ---------- 初始化 ----------
    def prepare(self) -> None:
        try:
            for d in (self.notes_dir, self.raw_dir, self.attachments_dir,
                      self.media_dir, self.state_dir / "runs", self.cache_dir):
                d.mkdir(parents=True, exist_ok=True)
            probe = self.state_dir / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            raise OutputNotWritable(
                f"输出目录不可写：{self.root}（{exc}）",
                hint="换一个目录，或检查磁盘权限/剩余空间",
            )

    # ---------- 状态 ----------
    def load_state(self) -> dict:
        if not self.state_file.is_file():
            return {"version": 1, "items": {}}
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "items": {}}
        data.setdefault("items", {})
        return data

    def save_state(self, state: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def record(self, state: dict, content: Content, *, note_path: Path | None,
               note_text: str | None, status: str,
               requirements: dict | None = None,
               done: dict | None = None,
               note_uploaded=True) -> None:
        items = state.setdefault("items", {})
        entry = items.setdefault(f"{content.platform}:{content.content_id}", {})
        entry.update({
            "platform": content.platform,
            "content_id": content.content_id,
            "title": content.title,
            "author": content.author,
            "url": content.url_resolved,
            "status": status,
            "source": content.source.value,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note_path": str(note_path.relative_to(self.root)) if note_path else None,
            "note_sha256": sha256_text(note_text) if note_text else None,
            "raw_path": entry.get("raw_path"),
            "warnings": content.warnings,
            "errors": content.errors,
            # requirements = 本次「请求」的能力；done = 实际「完成」的步骤。
            # 两者分开记，模型摘要失败回落时才不会假装完成。
            "requirements": dict(requirements or {}),
            "done": dict(done or {}),
        })
        entry["runs"] = int(entry.get("runs", 0)) + 1

    # ---------- 内容缓存（补做步骤时复用，不重复计费） ----------
    def _cache_file(self, key: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in key)
        return self.cache_dir / f"{safe}.json"

    def load_cache(self, key: str) -> dict | None:
        path = self._cache_file(key)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def save_cache(self, key: str, data: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_file(key)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    # ---------- 去重判定 ----------
    def check_existing(self, key: str) -> dict:
        """返回 {exists, note_path, note_modified, entry}。"""
        state = self.load_state()
        entry = state.get("items", {}).get(key)
        if not entry or not entry.get("note_path"):
            return {"exists": False, "note_path": None, "note_modified": False, "entry": entry}
        note_path = self.root / entry["note_path"]
        if not note_path.is_file():
            return {"exists": False, "note_path": None, "note_modified": False, "entry": entry}
        current = sha256_text(note_path.read_text(encoding="utf-8"))
        modified = bool(entry.get("note_sha256")) and current != entry["note_sha256"]
        return {"exists": True, "note_path": note_path, "note_modified": modified,
                "entry": entry}

    # ---------- 路径分配 ----------
    def note_path(self, content: Content, slug: str, *, stamp: str) -> Path:
        """文件名带内容 id：同日期同标题的两条不同内容不会互相覆盖。"""
        short = "".join(ch for ch in content.content_id if ch.isalnum() or ch in "-_")[:12]
        short = short or "unknown"
        return self.notes_dir / f"{stamp}_{content.platform}_{short}_{slug}.md"

    def raw_path(self, content: Content) -> Path:
        return self.raw_dir / f"{content.content_id}_content.txt"

    def attach_dir(self, content: Content) -> Path:
        d = self.attachments_dir / content.content_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def media_path(self, content: Content, suffix: str = ".mp4") -> Path:
        return self.media_dir / f"{content.content_id}{suffix}"


def slugify(text: str, limit: int = 40) -> str:
    """文件名用：去标点与空白，保持中文可读，限制长度。"""
    keep = []
    for ch in text:
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff":   # 字母数字 + 汉字
            keep.append(ch)
        elif ch in " -_":
            keep.append("-")
    slug = "".join(keep).strip("-")
    slug = "-".join(part for part in slug.split("-") if part)
    return slug[:limit] or "untitled"
