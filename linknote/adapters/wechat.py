"""微信公众号文章适配器：公开文章直接 GET，不需要登录。

注意：公众号对频繁访问有风控，遇到"环境异常/需要验证"时不要反复重试，
如实报告需要人工在浏览器里打开一次。
"""
from __future__ import annotations

import datetime as dt
import re
import time
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

import requests

from ..config import Config
from ..errors import InvalidLink, LoginRequired, NetworkFailure, NotAccessible
from ..html2md import html_to_markdown, html_to_text
from ..models import Content, Source

FAIL_MARKERS = [
    ("该内容已被发布者删除", "文章已被发布者删除"),
    ("此内容因违规无法查看", "文章因违规无法查看"),
    ("该公众号已迁移", "公众号已迁移，链接失效"),
    ("参数错误", "链接参数错误"),
    ("此内容被多人投诉", "文章被投诉屏蔽"),
]
LOGIN_MARKERS = ["环境异常", "完成验证后即可继续访问", "去验证", "请输入验证码"]


class WechatAdapter:
    def __init__(self, cfg: Config, logger, workdir: Path):
        self.cfg = cfg
        self.log = logger
        self.workdir = workdir

    def fetch(self, target, *, need_media: bool) -> Content:  # noqa: ARG002
        html = self._get(target.url_resolved)
        return self._parse(html, target)

    # ---------- 网络 ----------
    def _get(self, url: str) -> str:
        headers = {
            "User-Agent": self.cfg.user_agent,
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        last_error = ""
        for attempt in range(self.cfg.retries + 1):
            try:
                r = requests.get(url, headers=headers, timeout=self.cfg.http_timeout)
            except requests.RequestException as exc:
                last_error = f"网络错误：{exc}"
                time.sleep(min(2 ** attempt * 2, 8))
                continue

            text = r.text
            if r.status_code == 404:
                raise NotAccessible("文章不存在（HTTP 404）")
            if r.status_code == 429:
                last_error = "被限流（HTTP 429）"
                time.sleep(min(2 ** attempt * 5, 20))
                continue
            if r.status_code >= 500:
                last_error = f"服务端错误（HTTP {r.status_code}）"
                time.sleep(min(2 ** attempt * 2, 8))
                continue

            for marker, reason in FAIL_MARKERS:
                if marker in text:
                    raise NotAccessible(reason, hint="确认链接在浏览器里还能正常打开")
            if any(m in text for m in LOGIN_MARKERS):
                raise LoginRequired(
                    "公众号要求人工验证（环境异常），无法自动获取",
                    hint="在浏览器里打开一次该链接完成验证后重试；本工具不做验证码绕过",
                )
            if 'id="js_content"' not in text and "rich_media_content" not in text:
                raise InvalidLink(
                    "页面里没有找到正文区域，可能不是公众号文章",
                    hint="确认链接形如 https://mp.weixin.qq.com/s/XXXXXXXX",
                )
            return text
        raise NetworkFailure(f"获取文章失败：{last_error}", hint="检查网络或代理设置")

    # ---------- 解析 ----------
    def _parse(self, html: str, target) -> Content:
        title = self._meta(html, "og:title") or self._first(
            html, r'id="activity-name"[^>]*>(.*?)<') or "（无标题）"
        author = self._first(html, r'var\s+nickname\s*=\s*"([^"]*)"') or \
            self._first(html, r'id="js_name"[^>]*>\s*([^<]+?)\s*<') or ""
        published = self._publish_time(html)
        desc = self._meta(html, "og:description")

        inner = self._content_html(html)
        # 关键：属性里的 &amp; 要还原，否则和 html2md 解析出的地址对不上，图片替换会失效
        images = [unescape(u) for u in re.findall(r'data-src="([^"]+)"', inner)]
        image_map = self._download_images(images, target.content_id)
        markdown = html_to_markdown(inner, image_map)
        plain = html_to_text(inner)

        content = Content(
            platform="wechat",
            content_id=target.content_id,
            title=title.strip(),
            author=author.strip(),
            url_raw=target.url_raw,
            url_resolved=target.url_resolved,
            published_at=published,
            fetched_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            source=Source.NATIVE_TEXT,
            text=plain,
            text_note="公众号文章原生正文（未经转写，逐字取自页面）",
            extras={
                "公众号": author.strip(),
                "摘要（平台自带）": desc,
                "正文 Markdown": markdown,
                "图片数": len(images),
            },
        )
        if not plain:
            content.warnings.append("正文区域是空的（可能是纯图片文章或内容被折叠）")
        if images and not image_map:
            content.warnings.append("文章有图片，但一张都没下载成功（可能需要 referer 或已失效）")
        return content

    @staticmethod
    def _meta(html: str, prop: str) -> str:
        m = re.search(rf'<meta[^>]+property="{re.escape(prop)}"[^>]+content="([^"]*)"', html)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _first(html: str, pattern: str) -> str:
        m = re.search(pattern, html, re.S)
        if not m:
            return ""
        from html import unescape
        return unescape(m.group(1)).strip()

    @staticmethod
    def _publish_time(html: str) -> str | None:
        m = re.search(r'var\s+ct\s*=\s*"(\d{9,})"', html)
        if m:
            return dt.datetime.fromtimestamp(int(m.group(1))).strftime("%Y-%m-%d %H:%M")
        m = re.search(r'id="publish_time"[^>]*>\s*([^<]+?)\s*<', html)
        return m.group(1).strip() if m else None

    @staticmethod
    def _content_html(html: str) -> str:
        start = html.find('id="js_content"')
        if start == -1:
            start = html.find("rich_media_content")
        if start == -1:
            return ""
        start = html.find(">", start) + 1
        ends = [html.find(marker, start) for marker in
                ('id="js_pc_qr_code"', 'class="rich_media_tool"', 'id="js_tags"',
                 'class="rich_media_area_extra"')]
        ends = [e for e in ends if e > 0]
        end = min(ends) if ends else len(html)
        return html[start:end]

    def _download_images(self, urls: list[str], cid: str) -> dict[str, str]:
        """下载正文图片，返回 {原地址: 相对路径}。失败的图保留远程地址。"""
        if not urls:
            return {}
        out_dir = self.workdir / f"{cid}_img"
        out_dir.mkdir(parents=True, exist_ok=True)
        mapping: dict[str, str] = {}
        headers = {"User-Agent": self.cfg.user_agent,
                   "Referer": "https://mp.weixin.qq.com/"}
        seen = 0
        for url in dict.fromkeys(urls):          # 去重但保持顺序
            seen += 1
            try:
                r = requests.get(url, headers=headers, timeout=self.cfg.http_timeout)
                if r.status_code != 200 or len(r.content) < 2048:
                    continue
                ext = ".png" if url.lower().endswith(".png") else ".jpg"
                name = f"img_{seen:02d}{ext}"
                (out_dir / name).write_bytes(r.content)
                mapping[url] = name
            except requests.RequestException:
                continue
        if mapping:
            self.log.info("公众号：下载图片 %d/%d 张", len(mapping), len(set(urls)))
        return mapping

    @staticmethod
    def host_of(url: str) -> str:
        return (urlparse(url).hostname or "").lower()
