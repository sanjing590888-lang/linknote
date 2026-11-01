"""0.1.2 回归测试：补齐 0.1.1 复核发现的三类问题。

全部为**模拟**（假适配器、假转写、拦死网络的 conftest），
只证明代码路径正确，不代表抖音 / 公众号平台端到端可用。
"""
from __future__ import annotations

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
            title=kw.pop("title", "模拟标题"), author=kw.pop("author", "模拟作者"),
            url_raw=target.url_raw, url_resolved=target.url_resolved,
            published_at=kw.pop("published_at", "2026-11-01 10:00"),
            fetched_at="2026-11-01 20:00",
            source=kw.pop("source", Source.ASR),
            text=kw.pop("text", ""),
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
    """数一数收费步骤被调了几次。"""
    c = {"transcribe": 0, "digest": 0}

    def counting_transcribe(audio, cfg, logger=None):
        c["transcribe"] += 1
        return "转写出来的正文，长度足够，用来测试补做时不会重复转写。"

    real_digest = pl.make_digest

    def counting_digest(text, cfg, **kw):
        c["digest"] += 1
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


# ---------------- 1. 保留原片：第二次要就得真留下来 ----------------

def test_keep_media_second_run_actually_downloads(tmp_path, fake, counts):
    media = tmp_path / "src.mp4"
    media.write_bytes(b"fake-mp4-bytes")
    fake.payload = {"media_path": str(media), "text": ""}

    cfg = _cfg(tmp_path, keep_media=False)
    r1 = pl.ingest(URL, cfg)
    assert r1.status == "complete"
    assert not list((tmp_path / "media").glob("*.mp4")), "第一次没要求保留"
    transcribe_1, digest_1 = counts["transcribe"], counts["digest"]

    # 第二次只要 --keep-media：不能因为「上次 complete」就跳过
    r2 = pl.ingest(URL, cfg, keep_media=True)
    assert r2.status != "skipped"
    kept = list((tmp_path / "media").glob("*.mp4"))
    assert len(kept) == 1 and kept[0].stat().st_size > 0, "原片必须真的落地"

    # 补做时复用已成功的转写与摘要，不重复花钱
    assert counts["transcribe"] == transcribe_1
    assert counts["digest"] == digest_1
    assert len(fake.fetches) == 2          # 取内容一次（为了拿视频）

    # 第三次参数没变 → 这次才允许 skipped
    r3 = pl.ingest(URL, cfg, keep_media=True)
    assert r3.status == "skipped"


def test_missing_media_file_is_repaired_not_skipped(tmp_path, fake, counts):
    media = tmp_path / "src.mp4"
    media.write_bytes(b"fake-mp4-bytes")
    fake.payload = {"media_path": str(media), "text": ""}
    cfg = _cfg(tmp_path, keep_media=True)

    r1 = pl.ingest(URL, cfg)
    assert r1.status == "complete"
    kept = list((tmp_path / "media").glob("*.mp4"))
    assert kept
    kept[0].unlink()                        # 用户把原片删了

    r2 = pl.ingest(URL, cfg)                # 状态说 complete，但文件不在
    assert r2.status != "skipped", "产物缺失必须补回来"
    assert list((tmp_path / "media").glob("*.mp4")), "原片必须重新落地"


# ---------------- 2. 摘要模型失败：不许假装完成，下次只补摘要 ----------------

def test_digest_fallback_is_partial_and_then_repaired(tmp_path, fake, counts, monkeypatch):
    def boom(text, cfg):
        raise RuntimeError("模型 502")

    monkeypatch.setattr(sm, "llm_digest", boom)
    fake.payload = {"text": "一段足够长的正文，用来测试摘要回落到抽取式之后还能不能补做。"}
    cfg = _cfg(tmp_path, llm_base_url="https://llm.example/v1",
               llm_model="fake-llm", llm_api_key="k")

    r1 = pl.ingest(URL, cfg)
    assert r1.status == "partial", "模型没成功就不能记成 complete"
    assert any("抽取式" in w for w in r1.warnings)
    note1 = Path(r1.note_path).read_text(encoding="utf-8")
    assert "抽取式" in note1

    transcribe_1, digest_1, fetch_1 = counts["transcribe"], counts["digest"], len(fake.fetches)

    # 服务恢复
    def ok(text, cfg):
        return sm.Digest(mode="llm", model="fake-llm",
                         summary=["模型写的一句摘要"], keypoints=["模型整理的一条要点"])

    monkeypatch.setattr(sm, "llm_digest", ok)
    r2 = pl.ingest(URL, cfg)
    assert r2.status == "complete"
    assert counts["digest"] == digest_1 + 1        # 只补摘要，调一次
    assert counts["transcribe"] == transcribe_1    # 没有重新转写
    assert len(fake.fetches) == fetch_1            # 没有重新取内容 / 下载
    assert "模型写的一句摘要" in Path(r2.note_path).read_text(encoding="utf-8")

    # 再跑一次：这次真的齐全了 → skipped
    assert pl.ingest(URL, cfg).status == "skipped"


def test_extractive_by_choice_still_complete(tmp_path, fake, counts):
    fake.payload = {"text": "没配模型时用抽取式是用户自己的选择，不能算失败。"}
    cfg = _cfg(tmp_path)                    # 没有配 LLM
    r1 = pl.ingest(URL, cfg)
    assert r1.status == "complete"
    assert pl.ingest(URL, cfg).status == "skipped"


# ---------------- 3. 补做过程不重复已成功的收费步骤 ----------------

def test_asr_added_later_only_transcribes_once(tmp_path, fake, counts):
    media = tmp_path / "src.mp4"
    media.write_bytes(b"fake-mp4-bytes")
    fake.payload = {"media_path": str(media), "text": ""}   # 只有元信息

    cfg_off = Config(output_dir=tmp_path)                   # 没配 ASR
    r1 = pl.ingest(URL, cfg_off)
    assert r1.status == "failed"
    assert counts["transcribe"] == 0

    cfg_on = _cfg(tmp_path)
    r2 = pl.ingest(URL, cfg_on)
    assert r2.status == "complete"
    assert counts["transcribe"] == 1

    r3 = pl.ingest(URL, cfg_on)
    assert r3.status == "skipped"
    assert counts["transcribe"] == 1, "跳过时不能再调 ASR"


# ---------------- 4. 模拟测试必须离线 ----------------

def test_network_is_blocked():
    import requests
    with pytest.raises(AssertionError):
        requests.post("https://example.com/chat/completions", json={})
