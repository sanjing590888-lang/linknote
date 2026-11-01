"""极简 HTML → Markdown：只处理公众号文章里真实出现的标签，不追求通用。

支持的标签：p / br / h1-h4 / section / span / strong|b / em|i / blockquote /
ul|ol|li / img / a / code / pre / hr。其余标签按行内文本处理。
"""
from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

BLOCK_TAGS = {"p", "div", "section", "article", "h1", "h2", "h3", "h4",
              "h5", "h6", "blockquote", "li", "tr", "figure", "figcaption"}
SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe"}


class _Converter(HTMLParser):
    def __init__(self, image_map: dict[str, str] | None = None):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.image_map = image_map or {}
        self._skip_depth = 0
        self._list_stack: list[str] = []
        self._link_href: str | None = None
        self._in_pre = 0
        self._buf: list[str] = []

    # ---- 工具 ----
    def _flush(self, block: bool = False) -> None:
        text = "".join(self._buf)
        self._buf.clear()
        text = re.sub(r"[ \t\u3000]+", " ", text)
        if block:
            text = text.strip()
        if text:
            self.out.append(text)

    def _newline(self, count: int = 1) -> None:
        self._flush()
        self.out.append("\n" * count)

    # ---- 事件 ----
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        if tag in BLOCK_TAGS:
            self._newline(2 if tag in ("p", "blockquote", "h1", "h2", "h3", "h4") else 1)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush()
            self.out.append("#" * int(tag[1]) + " ")
        elif tag == "br":
            self._newline(1)
        elif tag in ("strong", "b"):
            self._flush(); self.out.append("**")
        elif tag in ("em", "i"):
            self._flush(); self.out.append("*")
        elif tag == "code":
            self._flush(); self.out.append("`")
        elif tag == "pre":
            self._in_pre += 1; self._newline(2); self.out.append("```\n")
        elif tag == "blockquote":
            self._flush(); self.out.append("> ")
        elif tag in ("ul", "ol"):
            self._list_stack.append(tag)
        elif tag == "li":
            self._newline(1)
            marker = "1. " if self._list_stack and self._list_stack[-1] == "ol" else "- "
            self.out.append(marker)
        elif tag == "img":
            src = attrs.get("data-src") or attrs.get("src") or ""
            if src:
                local = self.image_map.get(src)
                alt = (attrs.get("alt") or "").strip()
                self._newline(2)
                self.out.append(f"![{alt}]({local or src})")
                self._newline(1)
        elif tag == "a":
            self._link_href = attrs.get("href") or None
            if self._link_href:
                self._flush(); self.out.append("[")
        elif tag == "hr":
            self._newline(2); self.out.append("---"); self._newline(2)

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return

        if tag in ("strong", "b"):
            self._flush(); self.out.append("**")
        elif tag in ("em", "i"):
            self._flush(); self.out.append("*")
        elif tag == "code":
            self._flush(); self.out.append("`")
        elif tag == "pre":
            self._flush(); self.out.append("\n```\n"); self._in_pre = max(0, self._in_pre - 1)
        elif tag == "a":
            if self._link_href:
                self._flush(); self.out.append(f"]({self._link_href})")
                self._link_href = None
        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            self._newline(1)
        elif tag in BLOCK_TAGS:
            self._newline(2 if tag in ("p", "blockquote", "h1", "h2", "h3", "h4") else 1)

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_pre:
            self.out.append(data)
            return
        self._buf.append(data)

    def result(self) -> str:
        self._flush()
        text = "".join(self.out)
        text = re.sub(r"\n{3,}", "\n\n", text)
        # 去掉公众号里常见的软换行残留
        text = re.sub(r"[ \t]+\n", "\n", text)
        return text.strip()


def html_to_markdown(html: str, image_map: dict[str, str] | None = None) -> str:
    parser = _Converter(image_map)
    parser.feed(html)
    parser.close()
    return parser.result()


def html_to_text(html: str) -> str:
    """给摘要算法看的纯文本：去标签、压空白。"""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|section|h[1-6]|li|blockquote)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
