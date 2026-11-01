"""来源识别与链接规范化：把各种分享形态收敛成（平台, 内容 id, 规范链接）。"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import requests

from .errors import InvalidLink, NetworkFailure, UnsupportedLink

DOUYIN_HOSTS = ("v.douyin.com", "www.douyin.com", "douyin.com",
                "www.iesdouyin.com", "iesdouyin.com")
WECHAT_HOSTS = ("mp.weixin.qq.com",)

_VIDEO_ID = re.compile(r"/(?:share/)?video/(\d{6,})")
_NOTE_ID = re.compile(r"/(?:share/)?note/(\d{6,})")
_MODAL_ID = re.compile(r"modal_id=(\d{6,})")
_WX_PATH = re.compile(r"^/s(?:/[\w\-]{6,})?$")


@dataclass
class Target:
    platform: str          # douyin | wechat
    content_id: str
    url_raw: str
    url_resolved: str

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.content_id}"


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def looks_like_url(text: str) -> bool:
    return bool(re.search(r"https?://\S+", text or ""))


def extract_url(text: str) -> str:
    """用户常常整段粘贴分享文案，取出里面第一个 http(s) 链接。"""
    m = re.search(r"https?://[^\s，。、）)】]+", text or "")
    if not m:
        raise InvalidLink("没有在输入里找到链接", hint="直接粘贴 https://... 开头的链接")
    return m.group(0).rstrip(".")


def normalize(raw: str, *, timeout: int = 30, retries: int = 2) -> Target:
    """识别链接来源；抖音短链会跟随跳转拿到真实 id。"""
    url = extract_url(raw)
    host = _host(url)
    if not host:
        raise InvalidLink(f"链接不合法：{url}")

    if host in WECHAT_HOSTS:
        return _normalize_wechat(url)
    if host in DOUYIN_HOSTS:
        return _normalize_douyin(url, timeout=timeout, retries=retries, raw=url)
    raise UnsupportedLink(
        f"暂不支持该来源：{host}",
        hint="第一版只支持抖音单条视频与微信公众号单篇文章",
    )


def _normalize_wechat(url: str) -> Target:
    parsed = urlparse(url)
    if not _WX_PATH.match(parsed.path or ""):
        raise UnsupportedLink(
            f"这不是公众号文章链接（路径 {parsed.path or '/'}）",
            hint="文章链接形如 https://mp.weixin.qq.com/s/XXXXXXXX",
        )
    # 保留必要参数（有些链接靠 __biz/mid/idx 定位），去掉分享追踪参数
    keep = {"__biz", "mid", "idx", "sn", "chksm", "scene", "srcid", "sharer_shareinfo",
            "sharer_shareinfo_first"}
    q = {k: v[0] for k, v in parse_qs(parsed.query).items() if k in keep}
    query = "&".join(f"{k}={v}" for k, v in q.items())
    resolved = f"https://mp.weixin.qq.com{parsed.path}" + (f"?{query}" if query else "")
    return Target("wechat", _wechat_content_id(parsed, q), url, resolved)


def _wechat_content_id(parsed, q: dict) -> str:
    """文章身份：优先路径里的短 id，其次 __biz+mid+idx，最后 sn。

    分享追踪参数（scene / chksm / sharer_shareinfo* / srcid）一律不参与身份，
    否则同一篇被不同人转发就成了不同内容。
    """
    seg = (parsed.path or "").rstrip("/").split("/")[-1]
    if seg and seg not in ("s", "mp"):
        return seg

    biz, mid, idx = q.get("__biz"), q.get("mid"), q.get("idx")
    if biz and mid:
        raw = f"{biz}|{mid}|{idx or '1'}"
        return "wx_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    sn = (q.get("sn") or "").strip()
    if sn:
        return "sn_" + sn

    raise InvalidLink(
        "这条公众号链接里没有稳定的文章标识（既没有 /s/<id>，也没有 __biz+mid+idx）",
        hint="用文章页右上角「复制链接」，或手机端分享出来的完整链接",
    )


def _normalize_douyin(url: str, *, timeout: int, retries: int, raw: str | None = None) -> Target:
    original = raw or url
    if _host(url) in ("v.douyin.com",):
        url = _follow(url, timeout=timeout, retries=retries)

    for pattern in (_VIDEO_ID, _NOTE_ID, _MODAL_ID):
        m = pattern.search(url)
        if m:
            return Target("douyin", m.group(1), original,
                          f"https://www.douyin.com/video/{m.group(1)}")

    # 短链没跳转成功时再试一次
    followed = _follow(url, timeout=timeout, retries=retries)
    for pattern in (_VIDEO_ID, _NOTE_ID):
        m = pattern.search(followed)
        if m:
            return Target("douyin", m.group(1), original,
                          f"https://www.douyin.com/video/{m.group(1)}")
    raise InvalidLink(
        "没能从链接里解析出抖音作品 id",
        hint="用手机端「分享 → 复制链接」拿到的链接最稳；网页地址需含 /video/<id>",
    )


def _follow(url: str, *, timeout: int, retries: int) -> str:
    headers = {"User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1")}
    last = None
    for _ in range(retries + 1):
        try:
            r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            return r.url
        except requests.RequestException as exc:      # 网络问题：有限重试
            last = exc
    raise NetworkFailure(f"短链跳转失败：{last}", hint="检查网络或代理设置")
