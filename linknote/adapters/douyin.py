"""抖音适配器。

为什么必须用浏览器：抖音 web 接口有签名/风控校验，纯 HTTP 请求（哪怕带 cookie）
会返回 "Blocked by ArgusSecurityPlugin Uifid Not Found"；分享页的 SSR 数据在新版视频里
也是空的（renderInSSR=false）。真实浏览器上下文里同一个接口能正常返回 JSON，
所以这里用 Playwright 打开作品页并截获 aweme/detail 响应。

用到的都是平台公开页面上正常加载的内容，不做任何绕过登录或风控的处理。
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path

from ..config import Config
from ..errors import LoginRequired, NetworkFailure, NotAccessible, UnsupportedLink
from ..models import Content, Source

VIDEO_URL = "https://www.douyin.com/video/{cid}"
DETAIL_API = ("https://www.douyin.com/aweme/v1/web/aweme/detail/"
              "?aweme_id={cid}&device_platform=webapp&aid=6383"
              "&channel=channel_pc_web&version_code=170400&version_name=17.4.0")

DESKTOP_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


class DouyinAdapter:
    def __init__(self, cfg: Config, logger, workdir: Path):
        self.cfg = cfg
        self.log = logger
        self.workdir = workdir

    # ---------- 对外入口 ----------
    def fetch(self, target, *, need_media: bool) -> Content:
        detail = self._detail(target.content_id)
        content = self._to_content(target, detail)

        if need_media:
            url = self._best_play_url(detail)
            if not url:
                content.warnings.append("没有取到可下载的视频地址（可能是图文作品或已下架）")
            else:
                try:
                    content.media_path = str(self._download(url, target.content_id))
                except Exception as exc:
                    content.warnings.append(f"视频下载失败：{exc}")
        return content

    # ---------- 取详情 ----------
    def _detail(self, cid: str) -> dict:
        """取作品详情。抖音前端偶发风控/超时，整体重试有限次数。"""
        last: Exception | None = None
        for attempt in range(self.cfg.retries + 1):
            wait_ms = 4000 + attempt * 4000
            try:
                return self._detail_once(cid, wait_ms=wait_ms)
            except (NotAccessible, NetworkFailure, LoginRequired) as exc:
                last = exc
                if attempt < self.cfg.retries:
                    self.log.warning("抖音：第 %d 次获取失败（%s），重试中…",
                                     attempt + 1, getattr(exc, "code", "error"))
                    time.sleep(3)
        assert last is not None
        raise last

    def _detail_once(self, cid: str, *, wait_ms: int = 4000) -> dict:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise NetworkFailure(
                "没有安装 playwright，抖音适配器无法工作",
                hint="pip install 'linknote[douyin]' && playwright install chromium",
            ) from exc

        captured: dict = {}
        with sync_playwright() as p:
            if self.cfg.douyin_cdp_url:
                self.log.info("抖音：连接到已有 Chrome %s", self.cfg.douyin_cdp_url)
                browser = p.chromium.connect_over_cdp(self.cfg.douyin_cdp_url)
                ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                page = ctx.new_page()
                close_browser = False
            else:
                browser = p.chromium.launch(headless=self.cfg.douyin_headless)
                ctx = browser.new_context(user_agent=DESKTOP_UA, locale="zh-CN",
                                          viewport={"width": 1280, "height": 900})
                page = ctx.new_page()
                close_browser = True

            def on_response(resp):
                if "/aweme/v1/web/aweme/detail/" in resp.url and "detail" not in captured:
                    try:
                        data = resp.json()
                        if data.get("aweme_detail"):
                            captured["detail"] = data["aweme_detail"]
                    except Exception:
                        pass

            page.on("response", on_response)
            try:
                self.log.info("抖音：打开作品页 %s", VIDEO_URL.format(cid=cid))
                self._goto(page, VIDEO_URL.format(cid=cid))
                page.wait_for_timeout(wait_ms)
                if "detail" not in captured:
                    self.log.debug("抖音：未截获响应，改为页内调用接口")
                    detail = page.evaluate(
                        """async (api) => {
                            try {
                                const r = await fetch(api, {credentials: 'include',
                                    headers: {referer: location.href}});
                                const j = await r.json();
                                return j.aweme_detail || null;
                            } catch (e) { return null; }
                        }""",
                        DETAIL_API.format(cid=cid),
                    )
                    if detail:
                        captured["detail"] = detail
                if "detail" not in captured:
                    body = page.content()[:2000]
                    if "验证" in body or "captcha" in body.lower():
                        raise LoginRequired(
                            "抖音要求人机验证，浏览器里需要先手动过一次",
                            hint="设置 LINKNOTE_DOUYIN_CDP_URL 复用你已登录的 Chrome："
                                 "chrome --remote-debugging-port=9333",
                        )
                    raise NotAccessible(
                        "没能取到抖音作品数据（作品可能已删除、设为私密，或页面结构变化）",
                        hint="用浏览器打开该链接确认还能看到；结构变化时需要更新适配器",
                    )
            finally:
                page.close()
                if close_browser:
                    browser.close()

        return captured["detail"]

    # ---------- 组装 ----------
    def _goto(self, page, url: str) -> None:
        """导航带一次重试：抖音首屏偶发超时，重试时用更宽松的等待条件。"""
        last = None
        for attempt, (wait, timeout) in enumerate((("domcontentloaded", 30000),
                                                   ("commit", 30000))):
            try:
                page.goto(url, wait_until=wait, timeout=timeout)
                return
            except Exception as exc:            # playwright TimeoutError 等
                last = exc
                self.log.warning("抖音：打开页面失败（第 %d 次，%s）", attempt + 1, wait)
        raise NetworkFailure(
            f"打不开抖音作品页：{last}",
            hint="检查网络或代理；headless 被拦时可用 LINKNOTE_DOUYIN_CDP_URL 复用已登录的 Chrome",
        )

    def _to_content(self, target, detail: dict) -> Content:
        author = detail.get("author") or {}
        stats = detail.get("statistics") or {}
        video = detail.get("video") or {}
        images = detail.get("images") or []

        created = detail.get("create_time")
        published = (dt.datetime.fromtimestamp(created).strftime("%Y-%m-%d %H:%M")
                     if created else None)

        desc = (detail.get("desc") or "").strip()
        # 平台会给一个干净的短标题；没有才退回 desc 第一句
        title = (detail.get("item_title") or "").strip()
        if not title:
            first = re.split(r"[。！？\n]", desc)[0].strip()
            title = (first[:36] + "…") if len(first) > 36 else first
        title = title or "（无标题）"

        chapters = []
        for ch in (detail.get("chapter_list") or []):
            ts = int(ch.get("timestamp") or 0) // 1000
            chapters.append({
                "time": f"{ts // 60:02d}:{ts % 60:02d}",
                "title": (ch.get("desc") or "").strip(),
                "detail": (ch.get("detail") or "").strip(),
            })

        content = Content(
            platform="douyin",
            content_id=target.content_id,
            title=title,
            author=author.get("nickname") or "",
            url_raw=target.url_raw,
            url_resolved=target.url_resolved,
            published_at=published,
            fetched_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            source=Source.NONE,
            extras={
                "作者抖音号": author.get("unique_id") or "",
                "作者粉丝数": author.get("follower_count"),
                "作品类型": "图文" if images else "视频",
                "时长秒": round((video.get("duration") or 0) / 1000, 1) or None,
                "完整文案": desc,
                "作者文案": (detail.get("caption") or "").strip(),
                "章节目录": chapters,
            },
            stats={
                "点赞": stats.get("digg_count"),
                "评论": stats.get("comment_count"),
                "转发": stats.get("share_count"),
                "收藏": stats.get("collect_count"),
            },
        )
        if images:
            content.warnings.append("这是图文作品，第一版只处理视频，未提取图片内容")
        content.text_note = "平台未提供字幕接口；本工具不解码视频画面，口播内容需音频转写获得"
        return content

    @staticmethod
    def _best_play_url(detail: dict) -> str:
        video = detail.get("video") or {}
        candidates = []
        for br in (video.get("bit_rate") or []):
            url = ((br.get("play_addr") or {}).get("url_list") or [None])[0]
            if url:
                candidates.append((br.get("bit_rate") or 0, url))
        if candidates:
            return max(candidates, key=lambda x: x[0])[1]
        return ((video.get("play_addr") or {}).get("url_list") or [""])[0]

    def _download(self, url: str, cid: str) -> Path:
        import requests

        out = self.workdir / f"{cid}.mp4"
        headers = {"Referer": "https://www.douyin.com/", "User-Agent": DESKTOP_UA}
        last = None
        for attempt in range(self.cfg.retries + 1):
            try:
                with requests.get(url, headers=headers, stream=True,
                                  timeout=self.cfg.http_timeout) as r:
                    r.raise_for_status()
                    with out.open("wb") as fh:
                        for chunk in r.iter_content(1 << 20):
                            fh.write(chunk)
                size = out.stat().st_size
                if size < 50_000:
                    raise NetworkFailure(f"下载文件过小（{size} 字节），可能被拒绝")
                self.log.info("抖音：视频已下载 %.1f MB", size / 1e6)
                return out
            except Exception as exc:
                last = exc
                time.sleep(min(2 ** attempt, 8))
        raise NetworkFailure(f"视频下载失败：{last}")


def unsupported(reason: str):
    raise UnsupportedLink(reason)
