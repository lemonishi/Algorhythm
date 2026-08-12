"""LeetCode statement HTML to Markdown.

Uses stdlib `html.parser` rather than a Markdown library, because the
dependency budget is three packages and the input is a narrow, predictable
subset of HTML.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_BLOCK_TAGS = {"p", "div", "ul", "ol", "pre", "br"}


class _StatementParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._in_pre = False
        self._pre_buffer: list[str] = []

    # -- helpers ----------------------------------------------------------

    def _emit(self, text: str) -> None:
        self.parts.append(text)

    # -- HTMLParser hooks -------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "pre":
            self._in_pre = True
            self._pre_buffer = []
        elif self._in_pre:
            return  # tags inside <pre> are decoration; drop them
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "code":
            self._emit("`")
        elif tag == "sup":
            self._emit("^")
        elif tag == "li":
            self._emit("\n- ")
        elif tag == "br":
            self._emit("\n")
        elif tag == "img":
            alt = attributes.get("alt") or ""
            src = attributes.get("src") or ""
            self._emit(f"\n\n![{alt}]({src})\n\n")
        elif tag in _BLOCK_TAGS:
            self._emit("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre":
            self._in_pre = False
            content = "".join(self._pre_buffer).strip("\n")
            self._emit(f"\n\n```\n{content}\n```\n\n")
        elif self._in_pre:
            return
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "code":
            self._emit("`")
        elif tag in _BLOCK_TAGS:
            self._emit("\n\n")

    def handle_data(self, data: str) -> None:
        if self._in_pre:
            self._pre_buffer.append(data)
        else:
            self._emit(data.replace("\xa0", " "))


def render_statement(html_text: str) -> str:
    if not html_text:
        return ""

    parser = _StatementParser()
    parser.feed(html_text)
    parser.close()
    text = "".join(parser.parts)

    # Collapse runs of spaces outside fenced blocks, then tidy blank lines.
    out_lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.strip() == "```":
            in_fence = not in_fence
            out_lines.append("```")
            continue
        out_lines.append(line.rstrip() if in_fence else re.sub(r"[ \t]+", " ", line).strip())

    joined = "\n".join(out_lines)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip()
