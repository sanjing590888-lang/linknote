import pytest

from linknote.errors import InvalidLink, UnsupportedLink
from linknote.normalize import extract_url, normalize


def test_extract_url_from_share_text():
    text = "8.79 复制打开抖音，看看【codexu的作品】... https://v.douyin.com/zmPKTHlg5tk/ 10/19 m@Q.Xz"
    assert extract_url(text) == "https://v.douyin.com/zmPKTHlg5tk/"


def test_extract_url_missing():
    with pytest.raises(InvalidLink):
        extract_url("没有链接的一段话")


def test_wechat_normalize_keeps_biz_params():
    url = ("https://mp.weixin.qq.com/s?__biz=MzA5&mid=123&idx=1&sn=abc&scene=21"
           "&utm_source=wechat")
    t = normalize(url)
    assert t.platform == "wechat"
    assert "utm_source" not in t.url_resolved
    assert "mid=123" in t.url_resolved


def test_wechat_short_path():
    t = normalize("https://mp.weixin.qq.com/s/1e3Y0n7R7vsjVTO-Fs3e7Q")
    assert t.platform == "wechat"
    assert t.content_id == "1e3Y0n7R7vsjVTO-Fs3e7Q"


def test_douyin_direct_video_url():
    t = normalize("https://www.douyin.com/video/7702807081379843338")
    assert t.platform == "douyin"
    assert t.content_id == "7702807081379843338"
    assert t.url_resolved == "https://www.douyin.com/video/7702807081379843338"


def test_douyin_modal_id():
    t = normalize("https://www.douyin.com/user/MS4wLjAB?modal_id=7702807081379843338")
    assert t.content_id == "7702807081379843338"


def test_unsupported_host():
    with pytest.raises(UnsupportedLink):
        normalize("https://www.bilibili.com/video/BV1xx411c7mD")
