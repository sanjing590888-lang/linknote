"""一次 ingest 的完整流程：识别 → 获取 → 转写 → 整理 → 导出 → 记录状态。

0.1.2 起把「请求的能力」和「实际完成的步骤」分开记：
- wanted：这次要什么（模式 / 转写模型 / 摘要模式 / 是否保留原片）
- done：上次实际做到了什么（含摘要是不是回落到抽取式）

只有 wanted 全部落实、产物文件都还在，才判定为可跳过；否则只补缺的那一步。
补做时优先复用上次已成功的转写与摘要，不重复花 ASR / 模型的钱。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .adapters import get_adapter
from .config import Config
from .errors import LinknoteError, TranscribeFailure, TranscribeNotConfigured
from .models import Content, Source
from .note import render
from .normalize import normalize
from .store import Store, slugify
from .summarize import Digest, digest as make_digest, extractive
from .transcribe import clean_transcript, extract_audio, transcribe


@dataclass
class Result:
    status: str                       # complete | partial | failed | skipped
    platform: str = ""
    title: str = ""
    note_path: str | None = None
    message: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "platform": self.platform,
            "title": self.title,
            "note_path": self.note_path,
            "message": self.message,
            "warnings": self.warnings,
        }


def ingest(raw_url: str, cfg: Config, *, force: bool = False,
           extract_only: bool = False, keep_media: bool | None = None,
           logger=None) -> Result:
    keep = cfg.keep_media if keep_media is None else keep_media
    keep_requested = bool(keep)
    if extract_only:
        # 仅提取优先：无论配置或命令行怎么说，都不下载视频、不转写、不调模型
        keep = False
    store = Store(cfg.output_dir)
    store.prepare()

    target = normalize(raw_url, timeout=cfg.http_timeout, retries=cfg.retries)
    if logger:
        logger.info("识别为 %s，内容 id %s", target.platform, target.content_id)

    existing = store.check_existing(target.key)
    entry = existing["entry"] or {}
    wanted = _wanted(cfg, extract_only, keep)
    done = dict(entry.get("done") or {})
    cache = _load_cache(store, target)

    media_abs = _artifact(store, entry.get("media"))
    if force:
        # --force = 真的重来一遍：不当缺口算，直接全部重做
        gaps = ["force"]
        need_fetch = True
    else:
        gaps = _gaps(done, wanted,
                     text=bool(cache and cache.get("text")),
                     media=bool(media_abs),
                     note=existing["exists"])
        can_resume = bool(cache and cache.get("text"))
        need_fetch = ((not can_resume) or "text" in gaps or "transcribe" in gaps
                      or "media" in gaps or not existing["exists"])

    # 只有「上次确实全部做完 + 产物都还在 + 笔记没被改」才跳过
    if (not force and not existing["note_modified"]
            and entry.get("status") == "complete" and not gaps):
        return Result(
            status="skipped",
            platform=target.platform,
            title=entry.get("title", ""),
            note_path=str(existing["note_path"]),
            message="上次已全部完成且产物齐全，跳过（--force 可强制重跑）",
        )
    if existing["exists"] and not force and existing["note_modified"]:
        if logger:
            logger.warning("已有笔记被修改过，不覆盖，本次写入新文件")

    workdir = store.state_dir / "work" / target.content_id
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)

    # ---------- 获取内容 ----------
    if need_fetch:
        adapter = get_adapter(target.platform)(cfg, logger, workdir)
        need_media = wanted["asr"] != "off" or wanted["keep_media"]
        try:
            content: Content = adapter.fetch(target, need_media=need_media)
        except LinknoteError as exc:
            if logger:
                logger.error("获取失败（%s）：%s", exc.code, exc.message)
            return Result(status="failed", platform=target.platform,
                          message=f"[{exc.code}] {exc.message}"
                                  + (f"｜{exc.hint}" if exc.hint else ""),
                          warnings=list(exc.partial))

        had_media = bool(content.media_path)
        if cache and cache.get("text") and not force and "transcribe" not in gaps:
            # 上次的转写已经成功过：直接复用，不再调 ASR
            _restore_text(content, cache)
            if logger:
                logger.info("复用上次的转写文本，跳过 ASR")
        elif content.media_path and wanted["asr"] != "off":
            _try_transcribe(content, cfg, workdir, logger, keep=keep)
            done["asr"] = wanted["asr"] if content.text.strip() else "failed"
        elif (wanted["asr"] == "off" and not extract_only
              and target.platform == "douyin" and not content.has_text):
            content.warnings.append(
                "未配置转写服务，抖音视频只取得了元信息，**没有口播内容**；"
                "配置 LINKNOTE_ASR_* 后可补全"
            )
        if wanted["asr"] != "off" and not had_media:
            # 这次没有可转写的音频（图文作品、平台没给视频等）：转写项不构成缺口
            done["no_audio"] = True

        attach_rel, body_markdown = _export_media(content, store, workdir, keep, logger)
    else:
        # 只补摘要之类的轻量步骤：不联网取内容，直接用上次缓存
        assert cache is not None
        content = _content_from_cache(target, cache)
        attach_rel = cache.get("attach_rel")
        body_markdown = cache.get("body_markdown")
        if logger:
            logger.info("复用上次的正文 / 附件，本次只补做未完成的步骤")

    done["text"] = bool(content.text.strip())

    if extract_only and keep_requested:
        content.warnings.append(
            "参数冲突：--extract-only 优先，本次没有下载视频、没有转写、没有调用摘要模型；"
            "要保留原片请去掉 --extract-only 再跑一次")

    # ---------- 原始文本落盘 ----------
    raw_rel = None
    if content.text.strip():
        raw_file = store.raw_path(content)
        header = ("# 原始转写（ASR，非逐字准确）\n" if content.source is Source.ASR
                  else "# 原始正文（取自页面）\n")
        raw_file.write_text(header + content.text.strip() + "\n", encoding="utf-8")
        raw_rel = _rel(raw_file, store.root)

    # ---------- 摘要 ----------
    text_sha = _sha(content.text)
    if extract_only:
        # 只提取：绝不调用摘要模型（会花钱），也不让 digest 有机会发起请求
        digest = extractive(content.text)
        digest.warnings.insert(
            0, "本次为 --extract-only：没有调用摘要模型、没有转写、没有下载视频")
    elif (cache and cache.get("digest") and not force
          and done.get("digest") == wanted["digest"]
          and not done.get("digest_fallback")
          and cache["digest"].get("input_sha256") == text_sha):
        # 只有「摘要模式相同 + 送进去的正文一字没变」才复用；
        # 光模型名字一样不算，换了 ASR 模型正文会变，必须重做摘要
        digest = _digest_from_cache(cache["digest"])
        if logger:
            logger.info("复用上次的摘要，没有重复调用模型")
    else:
        digest = make_digest(content.text, cfg, logger=logger)

    if digest.mode == "llm":
        done["digest"] = f"llm:{digest.model or cfg.llm_model}"
        done["digest_fallback"] = False
    else:
        done["digest"] = "extractive"
        done["digest_fallback"] = bool(getattr(digest, "fallback", False))
        if done["digest_fallback"] and not extract_only:
            # 模型没成功就是没成功：状态降为 partial，下次只补摘要
            digest.warnings = []          # 详情统一写进处理说明，避免三行重复
            content.warnings.append(
                "摘要模型这次没成功，笔记用的是抽取式摘要（机械抽句），不代表模型整理；"
                "模型恢复后重跑会只补摘要，不重新下载或转写"
                + (f"（原因：{digest.fallback_reason}）" if digest.fallback_reason else ""))

    # ---------- 渲染 ----------
    media_rel = None
    media_path = content.media_path
    if media_path and keep:
        media_rel = _link(_rel(Path(media_path), store.root))

    stamp = re.sub(r"[^\d\-]", "", (content.published_at or content.fetched_at)[:10]) \
        or dt.datetime.now().strftime("%Y-%m-%d")
    # 文件名优先沿用上次记录的路径：标题微调不该在目录里多出一份孤档
    if existing["note_path"]:
        note_file = Path(existing["note_path"])
    else:
        note_file = store.note_path(content, slugify(content.title), stamp=stamp)

    # 覆盖保护不依赖状态文件：只要文件已经在那儿，就绝不静默覆盖
    if note_file.exists():
        owned = existing["exists"] and not existing["note_modified"]
        if not owned:
            # 手改过的笔记永远不覆盖，--force 也不行
            reason = ("已有笔记被手动改过" if existing["note_modified"]
                      else "同名文件已存在但不在任务记录里")
            note_file = _rerun_name(note_file)
            content.warnings.append(
                f"{reason}，本次写入 {note_file.name}，原文件未改动")
        elif force:
            backup = note_file.with_suffix(".md.bak")
            note_file.replace(backup)
            if logger:
                logger.info("覆盖前已备份 → %s", backup.name)
        # owned 且非 force：上次是我们自己写的、用户没动过（failed / partial），原地重写

    note_text = render(
        content, digest,
        raw_rel=_link(raw_rel) if raw_rel else None, media_rel=media_rel,
        attach_rel=attach_rel, body_markdown=body_markdown, tool_version=__version__,
        dialect=cfg.dialect, frontmatter=cfg.frontmatter,
    )
    note_file.write_text(note_text, encoding="utf-8")
    if logger:
        logger.info("笔记已写入 %s", note_file)

    # ---------- 状态 ----------
    state = store.load_state()
    store.record(state, content, note_path=note_file, note_text=note_text,
                 status=content.status.value, requirements=wanted, done=done)
    entry = state["items"][target.key]
    entry["raw_path"] = raw_rel
    if attach_rel:
        entry["attachments"] = attach_rel
    if media_rel:
        entry["media"] = _rel(Path(content.media_path), store.root)
        entry["media_kept"] = True
    store.save_state(state)

    store.save_cache(target.key, _cache_payload(content, cache, digest, text_sha,
                                                raw_rel, attach_rel, body_markdown))

    if not keep:
        shutil.rmtree(workdir, ignore_errors=True)

    status = content.status.value
    msg = {
        "complete": "完成",
        "partial": "部分完成（见处理说明）",
        "failed": "失败：没有拿到正文或口播内容",
    }[status]
    return Result(status=status, platform=target.platform, title=content.title,
                  note_path=str(note_file), message=msg,
                  warnings=list(content.warnings) + list(content.errors))


# ---------------- 能力需求与缺口 ----------------

def _wanted(cfg: Config, extract_only: bool, keep: bool) -> dict:
    """本次任务请求的能力。保留原片也算一种产物需求。"""
    return {
        "mode": "extract-only" if extract_only else "full",
        "asr": "off" if extract_only or not cfg.asr_enabled else cfg.asr_model,
        "digest": "extractive" if extract_only or not cfg.llm_enabled
                  else f"llm:{cfg.llm_model}",
        "keep_media": bool(keep),
    }


def _gaps(done: dict, wanted: dict, *, text: bool, media: bool, note: bool) -> list[str]:
    """还缺什么。空列表 = 这次不用重跑。"""
    gaps = []
    if not note:
        gaps.append("note")
    if not text:
        gaps.append("text")
    asr_ok = (wanted["asr"] == "off"
              or done.get("asr") == wanted["asr"]
              or done.get("no_audio"))
    if not asr_ok:
        gaps.append("transcribe")
    if wanted["keep_media"] and not media:
        gaps.append("media")
    if done.get("digest") != wanted["digest"] or done.get("digest_fallback"):
        gaps.append("digest")
    return gaps


def _artifact(store: Store, rel: str | None) -> Path | None:
    """把状态里记的相对路径还原成绝对路径，并确认文件真的在。"""
    if not rel:
        return None
    rel = str(rel).replace("\\", "/")
    while rel.startswith("../"):
        rel = rel[3:]
    path = store.root / rel
    return path if path.is_file() else None


# ---------------- 缓存 ----------------

def _load_cache(store: Store, target) -> dict | None:
    cache = store.load_cache(target.key)
    if not cache or cache.get("content_id") != target.content_id:
        return None
    return cache


def _cache_payload(content: Content, old: dict | None, digest: Digest,
                   text_sha: str, raw_rel: str | None, attach_rel: str | None,
                   body_markdown: str | None) -> dict:
    return {
        "content_id": content.content_id,
        "platform": content.platform,
        "title": content.title,
        "author": content.author,
        "url_raw": content.url_raw,
        "url_resolved": content.url_resolved,
        "published_at": content.published_at,
        "fetched_at": content.fetched_at,
        "source": content.source.value,
        "text": content.text,
        "text_sha256": text_sha,
        "asr_model": (content.extras.get("转写模型") or "") if content.source is Source.ASR else "",
        "text_note": content.text_note,
        "extras": content.extras,
        "media_path": content.media_path,
        "raw_rel": raw_rel,
        "attach_rel": attach_rel,
        "body_markdown": body_markdown,
        "digest": _digest_to_dict(digest, text_sha),
        "version": __version__,
        "previous_fetched_at": (old or {}).get("fetched_at"),
    }


def _content_from_cache(target, cache: dict) -> Content:
    content = Content(
        platform=target.platform,
        content_id=cache["content_id"],
        title=cache.get("title", ""),
        author=cache.get("author", ""),
        url_raw=cache.get("url_raw") or target.url_raw,
        url_resolved=cache.get("url_resolved") or target.url_resolved,
        published_at=cache.get("published_at"),
        fetched_at=cache.get("fetched_at", ""),
        source=Source(cache.get("source", "none")),
        text=cache.get("text", ""),
        text_note=cache.get("text_note", ""),
        extras=dict(cache.get("extras") or {}),
        media_path=cache.get("media_path"),
    )
    return content


def _restore_text(content: Content, cache: dict) -> None:
    content.text = cache.get("text", "")
    content.source = Source(cache.get("source", "none"))
    content.text_note = cache.get("text_note", "")
    for key in ("转写模型", "转写字数"):
        if key in (cache.get("extras") or {}):
            content.extras[key] = cache["extras"][key]


def _digest_to_dict(d: Digest, input_sha: str = "") -> dict:
    return {
        "mode": d.mode, "summary": list(d.summary), "keypoints": list(d.keypoints),
        "actions": list(d.actions), "model": d.model, "warnings": list(d.warnings),
        "fallback": bool(getattr(d, "fallback", False)),
        "fallback_reason": getattr(d, "fallback_reason", ""),
        "input_sha256": input_sha,
    }


def _digest_from_cache(data: dict) -> Digest:
    return Digest(
        mode=data.get("mode", "extractive"),
        summary=list(data.get("summary") or []),
        keypoints=list(data.get("keypoints") or []),
        actions=list(data.get("actions") or []),
        model=data.get("model", ""),
        warnings=list(data.get("warnings") or []),
        fallback=bool(data.get("fallback")),
        fallback_reason=data.get("fallback_reason", ""),
    )


# ---------------- 内部步骤 ----------------

def _rerun_name(path: Path) -> Path:
    """同名文件已存在时另存，绝不覆盖。"""
    stamp = dt.datetime.now().strftime("%H%M%S")
    candidate = path.with_name(f"{path.stem}.rerun-{stamp}.md")
    n = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}.rerun-{stamp}-{n}.md")
        n += 1
    return candidate


def _try_transcribe(content: Content, cfg: Config, workdir: Path, logger, *,
                    keep: bool) -> None:
    if not content.media_path:
        return
    media = Path(content.media_path)
    try:
        if logger:
            logger.info("抽取音轨 → %s", media.name)
        audio = extract_audio(media, workdir)
        if logger:
            logger.info("转写中（%s）", cfg.asr_model)
        text = clean_transcript(transcribe(audio, cfg, logger=logger))
        content.text = text
        content.source = Source.ASR
        content.text_note = (f"音频自动转写（模型 {cfg.asr_model}），"
                             "不是逐字原文，专有名词可能听错")
        content.extras["转写模型"] = cfg.asr_model
        content.extras["转写字数"] = len(text)
        if not keep:
            content.audio_removed = True
            content.media_path = None
    except TranscribeNotConfigured as exc:
        content.warnings.append(f"{exc.message}（{exc.hint}）")
    except TranscribeFailure as exc:
        content.warnings.append(f"转写失败：{exc.message}")
        if exc.hint:
            content.warnings.append(exc.hint)
        if not keep:
            content.media_path = None


def _export_media(content: Content, store: Store, workdir: Path,
                  keep: bool, logger) -> tuple[str | None, str | None]:
    """搬运附件；返回（附件目录相对路径, 正文 Markdown）。"""
    attach_rel: str | None = None
    body_markdown: str | None = None

    if content.platform == "wechat":
        src_dir = workdir / f"{content.content_id}_img"
        if src_dir.is_dir() and any(src_dir.iterdir()):
            dst = store.attach_dir(content)
            for f in src_dir.iterdir():
                shutil.copy2(f, dst / f.name)
            attach_rel = _rel(dst, store.root)
            body = content.extras.get("正文 Markdown") or ""
            # 把正文里的图片名改写成相对路径，保证点开就能看到
            for f in dst.iterdir():
                body = body.replace(f"]({f.name})", f"](../{attach_rel}/{f.name})")
            body_markdown = body
            content.extras["已下载图片"] = sum(1 for f in dst.iterdir() if f.is_file())

    if content.media_path and keep:
        dst = store.media_path(content, Path(content.media_path).suffix or ".mp4")
        shutil.copy2(content.media_path, dst)
        content.media_path = str(dst)
        if logger:
            logger.info("原片保留在 %s", _rel(dst, store.root))

    return attach_rel, body_markdown


def _sha(text: str) -> str:
    """摘要缓存的绑定点：正文变了，摘要就必须重做。"""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _rel(path: Path, root: Path) -> str:
    """相对路径统一用正斜杠：Markdown 链接在 Windows 上也不接受反斜杠。"""
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(path).replace("\\", "/")


def _link(rel: str) -> str:
    """笔记放在 notes/ 下，指向 raw/ attachments/ media/ 的链接都要先 ../。"""
    rel = rel.replace("\\", "/")
    return rel if rel.startswith("..") else f"../{rel}"
