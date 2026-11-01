from linknote.transcribe import clean_transcript


def test_clean_transcript_removes_emoji_and_tokens():
    raw = "🎼我用 NoteGen 申请到了 ChatGPT Pro<|zh|><|NEUTRAL|>，审核挺快🎵。"
    out = clean_transcript(raw)
    assert "🎼" not in out and "🎵" not in out
    assert "<|" not in out
    assert "NoteGen" in out


def test_clean_transcript_keeps_numbers_and_chinese():
    assert clean_transcript("少花 30% 到 60% 的 token。") == "少花 30% 到 60% 的 token。"
