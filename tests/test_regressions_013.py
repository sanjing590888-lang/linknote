"""0.1.3 回归测试：0.1.2 新增缓存带来的三个回归。

全部为**模拟**（假适配器、假转写、conftest 禁网），只证明代码路径正确，
不代表抖音 / 公众号平台端到端可用。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import linknote.summarize as sm
from linknote import pipeline as pl
from linknote.config import Config
from linknote.models import Content, Source
from linknote.normalize import Target

CID = "7702807081379843338"
URL = "https://v.douyin.com/x/"


class FakeAdapter:
    payload: dict = {}
    fetches: list[bool] = []

    def __init__(self, cfg, logger, workdir):
        self.workdir = workdir

    def fetch(self, target, need_media=False):
        FakeAdapter.fetches.append(need_media)
        kw = dict(FakeAdapter.payload)
        media = kw.pop("media_path", None)
        content = Content(
            platform="douyin", content_id=target.content_id,
            title=kw.pop("title", "模拟标题"), author="模拟作者",
            url_raw=target.url_raw, url_resolved=target.url_resolved,
            published_at="2026-11-01 10:00", fetched_at="2026-11-01 20:00",
            source=Source.ASR, text=kw.pop("text", ""),
        )
        content.media_path = media
        return content


@pytest.fixture
def fake(monkeypatch):
    FakeAdapter.payload = {}
    FakeAdapter.fetches = []
    monkeypatch.setattr(pl, "get_adapter", lambda platform: FakeAdapter)
    monkeypatch.setattr(pl, "normalize",
                        lambda raw, **kw: Target("douyin", CID, URL,
                                                 f"https://www.douyin.com/video/{CID}"))
    return FakeAdapter


@pytest.fixture
def counts(monkeypatch):
    c = {"transcribe": 0, "digest": 0, "digest_inputs": []}

    def counting_transcribe(audio, cfg, logger=None):
        c["transcribe"] += 1
        return (FakeAdapter.payload.get("transcribe_text")
                or "转写出来的正文，长度足够，用来测试补做时不会重复转写。")

    real_digest = pl.make_digest

    def counting_digest(text, cfg, **kw):
        c["digest"] += 1
        c["digest_inputs"].append(text)
        return real_digest(text, cfg, **kw)

    monkeypatch.setattr(pl, "transcribe", counting_transcribe)
    monkeypatch.setattr(pl, "extract_audio", lambda p, w: p)
    monkeypatch.setattr(pl, "make_digest", counting_digest)
    return c


def _cfg(tmp_path, **kw):
    base = dict(output_dir=tmp_path, asr_base_url="https://asr.example/v1",
                asr_model="fake-asr", asr_api_key="k")
    base.update(kw)
    return Config(**base)


def _media(tmp_path):
    p = tmp_path / "src.mp4"
    p.write_bytes(b"fake-mp4-bytes")
    return str(p)


def _digest_cache(tmp_path):
    files = list((tmp_path / ".linknote" / "cache").glob("*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text(encoding="utf-8"))


# ---------------- 1. --extract-only 优先于 keep_media ----------------

def test_extract_only_never_downloads_even_when_keep_media_configured(tmp_path, fake, counts):
    fake.payload = {"media_path": _media(tmp_path), "text": "平台自带正文，足够长，用于仅提取模式。"}
    cfg = _cfg(tmp_path, keep_media=True)          # 配置要求保留

    result = pl.ingest(URL, cfg, extract_only=True)

    assert fake.fetches == [False], "仅提取时不得要求适配器下载视频"
    assert not list((tmp_path / "media").glob("*.mp4")), "media/ 必须为空"
    assert counts["transcribe"] == 0, "仅提取不得调用 ASR"
    assert counts["digest"] == 0, "仅提取不得调用摘要模型"
    assert "extract-only" in Path(result.note_path).read_text(encoding="utf-8"), \
        "笔记里要写明本次是仅提取"


def test_extract_only_beats_keep_media_flag_and_says_so(tmp_path, fake, counts):
    fake.payload = {"media_path": _media(tmp_path), "text": "平台自带正文，足够长，用于仅提取模式。"}
    cfg = _cfg(tmp_path, keep_media=False)

    result = pl.ingest(URL, cfg, extract_only=True, keep_media=True)   # 命令行要保留

    assert fake.fetches == [False]
    assert not list((tmp_path / "media").glob("*.mp4")), "冲突时以仅提取为准，不静默下载"
    note = Path(result.note_path).read_text(encoding="utf-8")
    assert "保留" in note and "extract-only" in note, "参数冲突要明说，不能悄悄忽略"


# ---------------- 2. --force 必须真的重新执行 ----------------

def test_force_refetches_and_reprocesses(tmp_path, fake, counts):
    fake.payload = {"media_path": _media(tmp_path), "text": "第一次的正文，标记甲，足够长用来摘要。",
                    "transcribe_text": "第一次转写出来的正文，标记甲，足够长用来摘要。"}
    cfg = _cfg(tmp_path)
    r1 = pl.ingest(URL, cfg)
    assert r1.status == "complete"
    assert (fake.fetches, counts["transcribe"], counts["digest"]) == ([True], 1, 1)

    # 内容变了，用户要求强制重跑
    fake.payload = {"media_path": _media(tmp_path),
                    "text": "第二次的正文完全不同，标记乙，长度也够用来生成摘要。",
                    "transcribe_text": "第二次转写出来的正文，标记乙，长度也够用来生成摘要。"}
    r2 = pl.ingest(URL, cfg, force=True)

    assert len(fake.fetches) == 2, "--force 必须重新获取内容"
    assert counts["transcribe"] == 2, "--force 必须重新转写"
    assert counts["digest"] == 2, "--force 必须重新生成摘要"
    note = Path(r2.note_path).read_text(encoding="utf-8")
    assert "标记乙" in note and "标记甲" not in note
    assert Path(str(r2.note_path) + ".bak").exists(), "覆盖前要留备份"


def test_force_when_note_was_hand_edited_keeps_both(tmp_path, fake, counts):
    fake.payload = {"media_path": _media(tmp_path), "text": "第一次的正文，标记甲，足够长用来摘要。",
                    "transcribe_text": "第一次转写出来的正文，标记甲。"}
    cfg = _cfg(tmp_path)
    r1 = pl.ingest(URL, cfg)
    note = Path(r1.note_path)
    note.write_text(note.read_text(encoding="utf-8") + "\n我手写的一行。\n", encoding="utf-8")

    fake.payload = {"media_path": _media(tmp_path), "text": "第二次的正文，标记乙，长度也够用来生成摘要。",
                    "transcribe_text": "第二次转写出来的正文，标记乙。"}
    r2 = pl.ingest(URL, cfg, force=True)

    assert r2.note_path != r1.note_path, "手改过的笔记不能被覆盖"
    assert "我手写的一行" in note.read_text(encoding="utf-8"), "原笔记必须保留"
    assert "标记乙" in Path(r2.note_path).read_text(encoding="utf-8")


# ---------------- 3. 摘要缓存要绑定输入正文 ----------------

def test_asr_change_with_new_text_regenerates_digest(tmp_path, fake, counts, monkeypatch):
    media = _media(tmp_path)
    fake.payload = {"media_path": media, "text": ""}
    cfg1 = _cfg(tmp_path, asr_model="asr-one")

    def transcribe_one(audio, cfg, logger=None):
        counts["transcribe"] += 1
        return "模型一写出来的正文，标记甲，长度足够用来做摘要。"

    monkeypatch.setattr(pl, "transcribe", transcribe_one)
    r1 = pl.ingest(URL, cfg1)
    assert r1.status == "complete"
    first_digest_input = counts["digest_inputs"][-1]

    # 换 ASR 模型 → 正文变了
    cfg2 = _cfg(tmp_path, asr_model="asr-two")

    def transcribe_two(audio, cfg, logger=None):
        counts["transcribe"] += 1
        return "模型二写出来的完全不同的正文，标记乙，长度也够用来做摘要。"

    monkeypatch.setattr(pl, "transcribe", transcribe_two)
    r2 = pl.ingest(URL, cfg2)

    assert counts["transcribe"] == 2, "换了 ASR 模型就该重新转写"
    assert counts["digest"] == 2, "正文变了就不能复用旧摘要"
    assert "标记乙" in counts["digest_inputs"][-1]
    assert "标记甲" not in counts["digest_inputs"][-1]
    assert "标记乙" in Path(r2.note_path).read_text(encoding="utf-8")
    assert first_digest_input == counts["digest_inputs"][0], "第一次的摘要输入不该被改写"


def test_digest_cache_records_input_hash(tmp_path, fake, counts):
    fake.payload = {"media_path": _media(tmp_path), "text": ""}
    cfg = _cfg(tmp_path)
    pl.ingest(URL, cfg)

    cache = _digest_cache(tmp_path)
    text_hash = hashlib.sha256(cache["text"].encode("utf-8")).hexdigest()
    assert cache["digest"]["input_sha256"] == text_hash, "摘要缓存必须记下正文哈希"
    assert cache["asr_model"] == "fake-asr", "正文来源模型也要记下来"


def test_digest_reused_when_text_unchanged(tmp_path, fake, counts):
    fake.payload = {"media_path": _media(tmp_path), "text": ""}
    cfg = _cfg(tmp_path)
    pl.ingest(URL, cfg)
    transcribe_1, digest_1 = counts["transcribe"], counts["digest"]

    # 只是补原片，正文没变 → 摘要可以复用
    pl.ingest(URL, cfg, keep_media=True)
    assert counts["transcribe"] == transcribe_1, "正文没变就不该重新转写"
    assert counts["digest"] == digest_1, "正文没变就该复用摘要，不重复计费"
