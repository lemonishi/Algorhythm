"""LeetCode statement HTML to Markdown.

Uses stdlib `html.parser` rather than a Markdown library, because the
dependency budget is three packages and the input is a narrow, predictable
subset of HTML.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

# Tags whose open/close both become a paragraph break. `pre` and `br` are
# deliberately absent: each has an explicit branch in both handlers, and
# listing them here would double-emit for the self-closing `<br/>` form,
# which HTMLParser routes through handle_starttag AND handle_endtag.
_BLOCK_TAGS = {"p", "div", "ul", "ol"}


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

    def close(self) -> None:
        # An unclosed <pre> would otherwise discard its whole body silently.
        if self._in_pre:
            self.handle_endtag("pre")
        super().close()


def render_statement(html_text: str) -> str:
    if not html_text:
        return ""

    parser = _StatementParser()
    parser.feed(html_text)
    parser.close()
    text = "".join(parser.parts)

    # Collapse whitespace and blank-line runs, but only OUTSIDE fenced
    # blocks. Doing the blank-line collapse with a global regex over the
    # joined output would silently eat blank lines inside <pre>, undoing the
    # buffering above.
    out_lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.strip() == "```":
            in_fence = not in_fence
            out_lines.append("```")
            continue
        if in_fence:
            out_lines.append(line.rstrip())
            continue
        collapsed = re.sub(r"[ \t]+", " ", line).strip()
        if not collapsed and out_lines and not out_lines[-1]:
            continue  # already have a blank line here
        out_lines.append(collapsed)

    return "\n".join(out_lines).strip()
