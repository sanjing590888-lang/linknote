from pathlib import Path

from linknote.models import Content, Source, Status
from linknote.store import Store, sha256_text, slugify


def _content(cid="123"):
    return Content(platform="douyin", content_id=cid, title="测试标题｜竖线/斜杠",
                   author="某人", url_raw="https://v.douyin.com/x/",
                   url_resolved=f"https://www.douyin.com/video/{cid}",
                   source=Source.ASR, text="这是一段足够长的正文内容，用来满足最小长度要求。")


def test_slugify_strips_punctuation_keeps_chinese():
    assert slugify("测试标题｜竖线/斜杠") == "测试标题竖线斜杠"
    assert slugify("   ") == "untitled"
    assert len(slugify("长" * 100)) <= 40


def test_prepare_creates_layout(tmp_path: Path):
    store = Store(tmp_path / "out")
    store.prepare()
    for d in ("notes", "raw", "attachments", "media", ".linknote/runs"):
        assert (store.root / d).is_dir()


def test_record_and_check_existing(tmp_path: Path):
    store = Store(tmp_path / "out")
    store.prepare()
    content = _content()
    note = store.note_path(content, "标题", stamp="2026-11-01")
    note.write_text("# 笔记\n", encoding="utf-8")

    state = store.load_state()
    store.record(state, content, note_path=note, note_text="# 笔记\n", status="complete")
    store.save_state(state)

    check = store.check_existing("douyin:123")
    assert check["exists"] is True
    assert check["note_modified"] is False

    # 用户改了笔记 → 判定为已修改，不能覆盖
    note.write_text("# 笔记（我自己加的）\n", encoding="utf-8")
    check = store.check_existing("douyin:123")
    assert check["note_modified"] is True


def test_check_existing_unknown_key(tmp_path: Path):
    store = Store(tmp_path / "out")
    store.prepare()
    assert store.check_existing("douyin:999")["exists"] is False


def test_sha256_is_stable():
    assert sha256_text("abc") == sha256_text("abc")
    assert sha256_text("abc") != sha256_text("abd")


def test_content_status():
    c = _content()
    assert c.status is Status.COMPLETE
    c.warnings.append("缺封面")
    assert c.status is Status.PARTIAL
    c.text = "太短"
    assert c.status is Status.FAILED
