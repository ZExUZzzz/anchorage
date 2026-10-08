"""Minimal ANSI SGR parser: colours and bold, everything else stripped."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN = re.compile(
    r"\x1b\[(?P<sgr>[0-9;:]*)m"
    r"|\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[\x20-\x2f]+[\x30-\x7e]"
    r"|\x1b.?"
)


@dataclass(frozen=True, slots=True)
class Span:
    text: str
    fg: int | None
    bold: bool


def parse_ansi(text: str) -> list[Span]:
    spans: list[Span] = []
    fg: int | None = None
    bold = False
    pos = 0

    def push(chunk: str) -> None:
        if not chunk:
            return
        if spans and spans[-1].fg == fg and spans[-1].bold == bold:
            spans[-1] = Span(spans[-1].text + chunk, fg, bold)
        else:
            spans.append(Span(chunk, fg, bold))

    for match in _TOKEN.finditer(text):
        push(text[pos : match.start()])
        pos = match.end()
        codes = match.group("sgr")
        if codes is None:
            continue
        parts = re.split(r"[;:]", codes) if codes else ["0"]
        i = 0
        while i < len(parts):
            code = parts[i]
            i += 1
            if code in ("38", "48"):
                mode = parts[i] if i < len(parts) else ""
                width = {"5": 1, "2": 3}.get(mode, 0)
                args = parts[i + 1 : i + 1 + width]
                i += 1 + width
                if (
                    code == "38"
                    and mode == "5"
                    and len(args) == 1
                    and args[0].isdigit()
                    and int(args[0]) < 16
                ):
                    fg = int(args[0])
                continue
            if code in ("", "0"):
                fg, bold = None, False
            elif code == "1":
                bold = True
            elif code == "22":
                bold = False
            elif code == "39":
                fg = None
            elif code.isdigit() and 30 <= int(code) <= 37:
                fg = int(code) - 30
            elif code.isdigit() and 90 <= int(code) <= 97:
                fg = int(code) - 90 + 8
    push(text[pos:])
    return spans
