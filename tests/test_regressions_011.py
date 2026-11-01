"""0.1.1 回归测试：每条都对应 Codex 评审里的一项。

这些测试**全部是模拟**（假适配器、假转写），只证明代码路径正确，
不代表抖音 / 公众号平台端到端通过。真实流程另见 README 的实测记录。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from linknote import pipeline as pl
from linknote.config import Config
from linknote.models import Content, Source
from linknote.normalize import Target, normalize
from linknote.store import Store, slugify


# ---------------- 1. 公众号长链接身份 ----------------

LONG_A = ("https://mp.weixin.qq.com/s?__biz=MzA5MTIzNA==&mid=2650000001&idx=1"
          "&sn=aaaa1111&chksm=deadbeef&scene=21&sharer_shareinfo=xyz#wechat_redirect")
LONG_A_OTHER_SHARE = ("https://mp.weixin.qq.com/s?__biz=MzA5MTIzNA==&mid=2650000001&idx=1"
                      "&sn=aaaa1111&chksm=deadbeef&scene=1&sharer_shareinfo=other"
                      "&sharer_shareinfo_first=other2&srcid=1104")
LONG_B = ("https://mp.weixin.qq.com/s?__biz=MzA5MTIzNA==&mid=2650000002&idx=1"
          "&sn=bbbb2222&chksm=cafe&scene=21")


def test_wechat_long_link_has_real_id_not_s():
    t = normalize(LONG_A)
    assert t.content_id != "s"
    assert t.content_id.strip()


def test_wechat_same_article_same_id_across_share_params():
    assert normalize(LONG_A).content_id == normalize(LONG_A_OTHER_SHARE).content_id


def test_wechat_different_articles_different_id():
    assert normalize(LONG_A).content_id != normalize(LONG_B).content_id


def test_wechat_short_id_path_keeps_path_id():
    t = normalize("https://mp.weixin.qq.com/s/AbCdEfGhIjK")
    assert t.content_id == "AbCdEfGhIjK"


# ---------------- 2. 笔记路径含内容 id ----------------

def _content(cid="7702807081379843338", title="同一个标题", text="正文内容足够长，至少二十个字符才能算有文本。", **kw):
    c = Content(
        platform="douyin", content_id=cid, title=title, author="作者",
        url_raw="https://v.douyin.com/x/",
        url_resolved=f"https://www.douyin.com/video/{cid}",
        published_at="2026-11-01 10:00", fetched_at="2026-11-01 20:00",
        source=Source.ASR if not kw.get("native") else Source.NATIVE_TEXT,
        text=text,
    )
    return c


def test_note_path_contains_content_id(tmp_path):
    s = Store(tmp_path)
    a = _content("7702807081379843338")
    b = _content("7701779397988191515")
    pa = s.note_path(a, slugify(a.title), stamp="2026-11-01")
    pb = s.note_path(b, slugify(b.title), stamp="2026-11-01")
    assert pa != pb, "同日期同标题的不同内容必须落在不同文件"
    assert a.content_id[:12] in pa.name
    assert b.content_id[:12] in pb.name


def test_state_less_existing_file_is_not_overwritten(tmp_path, fake):
    """状态丢了但文件还在时，也不能覆盖（保护手动改过的旧笔记）。"""
    s = Store(tmp_path)
    s.prepare()
    c = _content()
    target_path = s.note_path(c, slugify(c.title), stamp="2026-11-01")
    target_path.write_text("用户手写的内容，不能被覆盖", encoding="utf-8")

    FakeAdapter.payload = {"title": "同一个标题",
                           "text": "这次运行拿到了足够长的正文，可以正常生成笔记。"}
    result, _ = _run(tmp_path)
    assert target_path.read_text(encoding="utf-8") == "用户手写的内容，不能被覆盖"
    assert Path(result.note_path) != target_path
    assert ".rerun-" in Path(result.note_path).name


# ---------------- 假适配器 ----------------

class FakeAdapter:
    """模拟适配器：不发网络请求。payload 由测试注入。"""
    payload: dict = {}
    seen_need_media: list[bool] = []

    def __init__(self, cfg, logger, workdir):
        self.workdir = workdir

    def fetch(self, target, need_media=False):
        FakeAdapter.seen_need_media.append(need_media)
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
    FakeAdapter.seen_need_media = []
    monkeypatch.setattr(pl, "get_adapter", lambda platform: FakeAdapter)
    monkeypatch.setattr(pl, "normalize",
                        lambda raw, **kw: Target("douyin", "7702807081379843338",
                                                 "https://v.douyin.com/x/",
                                                 "https://www.douyin.com/video/7702807081379843338"))
    return FakeAdapter


def _run(tmp_path, content=None, monkeypatch=None, *, force=False,
         extract_only=False, keep_media=None, cfg=None):
    """跑一次 ingest，返回 (result, cfg)。调用方需已装好 fake fixture。

    默认配置里开着 ASR：假适配器不返回媒体，于是不会真的转写，
    但「未配置转写」的警告也不会出现，方便断言 complete。
    """
    cfg = cfg or Config(output_dir=tmp_path, asr_base_url="https://asr.example/v1",
                        asr_model="fake-asr", asr_api_key="k")
    result = pl.ingest("https://v.douyin.com/x/", cfg, force=force,
                       extract_only=extract_only, keep_media=keep_media,
                       logger=None)
    return result, cfg


# ---------------- 3. --extract-only 不碰模型、不转写、不下载 ----------------

def test_extract_only_makes_no_model_or_asr_calls(tmp_path, fake, monkeypatch):
    calls = {"digest": 0, "transcribe": 0, "extract_audio": 0}

    def boom_digest(text, cfg, **kw):
        calls["digest"] += 1
        raise AssertionError("extract-only 不允许调用摘要（可能触发 LLM 计费）")

    def boom_transcribe(*a, **kw):
        calls["transcribe"] += 1
        raise AssertionError("extract-only 不允许转写")

    monkeypatch.setattr(pl, "make_digest", boom_digest)
    monkeypatch.setattr(pl, "transcribe", boom_transcribe)
    monkeypatch.setattr(pl, "extract_audio", boom_transcribe)

    cfg = Config(output_dir=tmp_path, asr_base_url="https://asr.example/v1",
                 asr_model="fake-asr", asr_api_key="k",
                 llm_base_url="https://llm.example/v1", llm_model="fake-llm",
                 llm_api_key="k")
    FakeAdapter.payload = {"media_path": str(tmp_path / "fake.mp4"),
                          "text": "这是一段够长的平台原生正文，用来占位测试。"}
    result, _ = _run(tmp_path, extract_only=True, cfg=cfg)

    assert calls == {"digest": 0, "transcribe": 0, "extract_audio": 0}
    assert FakeAdapter.seen_need_media == [False], "extract-only 不应触发视频下载"
    assert result.status in ("complete", "partial")


# ---------------- 4. 失败 / 部分完成必须能重试 ----------------

def test_failed_task_is_retried_not_skipped(tmp_path, fake):
    FakeAdapter.payload = {"text": ""}
    r1, _ = _run(tmp_path)
    assert r1.status == "failed"

    FakeAdapter.payload = {"text": "第二次拿到了完整正文，长度足够触发 complete 判定。"}
    r2, _ = _run(tmp_path)
    assert r2.status == "complete", "上次失败的任务不能因为存在旧笔记就跳过"


def test_partial_task_is_retried_not_skipped(tmp_path, fake):
    FakeAdapter.payload = {"text": "第一次只有半截内容，而且带警告需要重试一次看看效果。"}
    r1, _ = _run(tmp_path)
    # 手工把状态记成 partial，模拟缺口播
    store = Store(tmp_path)
    state = store.load_state()
    for entry in state["items"].values():
        entry["status"] = "partial"
    store.save_state(state)

    FakeAdapter.payload = {"text": "第二次内容完整了，长度足够并且没有警告，应该判为完成。"}
    r2, _ = _run(tmp_path)
    assert r2.status != "skipped"


def test_complete_task_with_same_requirements_is_skipped(tmp_path, fake):
    FakeAdapter.payload = {"text": "第一次就完整拿到了正文，长度足够，判定为 complete。"}
    r1, _ = _run(tmp_path)
    assert r1.status == "complete"
    r2, _ = _run(tmp_path)
    assert r2.status == "skipped"


def test_complete_task_reruns_when_requirements_change(tmp_path, fake, monkeypatch):
    """配了模型就该重跑；模型调用全部 mock，测试内不发真实请求。"""
    import linknote.summarize as sm

    FakeAdapter.payload = {"text": "第一次用抽取式摘要生成的笔记，内容完整。"}
    base = Config(output_dir=tmp_path, asr_base_url="https://asr.example/v1",
                  asr_model="fake-asr", asr_api_key="k")
    r1, _ = _run(tmp_path, cfg=base)
    assert r1.status == "complete"

    monkeypatch.setattr(sm, "llm_digest",
                        lambda text, cfg: sm.Digest(mode="llm", model="fake-llm",
                                                    summary=["模型摘要"], keypoints=["要点"]))
    FakeAdapter.payload = {"text": "第二次配置了模型，应该重跑而不是跳过，因为能力需求变了。"}
    cfg2 = Config(output_dir=tmp_path, asr_base_url="https://asr.example/v1",
                  asr_model="fake-asr", asr_api_key="k",
                  llm_base_url="https://llm.example/v1",
                  llm_model="fake-llm", llm_api_key="k")
    r2, _ = _run(tmp_path, cfg=cfg2)
    assert r2.status != "skipped", "配置能力变化后必须重跑"
    assert "模型摘要" in Path(r2.note_path).read_text(encoding="utf-8")


# ---------------- 5. keep_media 以本次任务为准 ----------------

def _media_test(tmp_path, fake, monkeypatch, *, cfg_keep, cli_keep):
    media = tmp_path / "src.mp4"
    media.write_bytes(b"fake")
    FakeAdapter.payload = {"media_path": str(media), "text": ""}
    monkeypatch.setattr(pl, "extract_audio", lambda p, w: tmp_path / "a.mp3")
    monkeypatch.setattr(pl, "transcribe",
                        lambda audio, cfg, logger=None: "转写出来的一段足够长的文字内容，用于测试。")
    cfg = Config(output_dir=tmp_path, keep_media=cfg_keep,
                 asr_base_url="https://asr.example/v1", asr_model="m", asr_api_key="k")
    _run(tmp_path, keep_media=cli_keep, cfg=cfg)
    return list((tmp_path / "media").glob("*.mp4"))


def test_keep_media_cli_true_beats_cfg_false(tmp_path, fake, monkeypatch):
    assert _media_test(tmp_path, fake, monkeypatch, cfg_keep=False, cli_keep=True)


def test_keep_media_cli_false_beats_cfg_true(tmp_path, fake, monkeypatch):
    assert not _media_test(tmp_path, fake, monkeypatch, cfg_keep=True, cli_keep=False)


# ---------------- 6. 相对链接必须从 notes/ 解析得到 ----------------

def _links(md: str) -> list[str]:
    import re
    return re.findall(r"\]\(([^)]+)\)", md)


def test_all_links_resolve_from_notes_dir(tmp_path):
    """目录链接、文件链接都要能点开；反斜杠要转成斜杠。"""
    from linknote.note import render
    from linknote.summarize import extractive

    s = Store(tmp_path)
    s.prepare()
    c = _content()
    (tmp_path / "raw").mkdir(exist_ok=True)
    (tmp_path / "raw" / f"{c.content_id}_content.txt").write_text("x", encoding="utf-8")
    attach = tmp_path / "attachments" / c.content_id
    attach.mkdir(parents=True)
    (attach / "img_01.jpg").write_bytes(b"jpg")
    media = tmp_path / "media" / f"{c.content_id}.mp4"
    media.parent.mkdir(exist_ok=True)
    media.write_bytes(b"mp4")

    note = render(c, extractive(c.text),
                  raw_rel=f"raw/{c.content_id}_content.txt",
                  media_rel=f"media/{c.content_id}.mp4",
                  attach_rel=f"attachments\\{c.content_id}",   # 故意用 Windows 反斜杠
                  body_markdown=f"![](../attachments/{c.content_id}/img_01.jpg)")
    note_file = tmp_path / "notes" / "n.md"
    note_file.parent.mkdir(exist_ok=True)
    note_file.write_text(note, encoding="utf-8")

    bad = []
    for link in _links(note):
        if link.startswith("http") or link.startswith("#"):
            continue
        target = (note_file.parent / link).resolve()
        if not target.exists():
            bad.append(link)
        if "\\" in link:
            bad.append(f"反斜杠链接：{link}")
    assert not bad, f"从 notes/ 解析不到的链接：{bad}"
