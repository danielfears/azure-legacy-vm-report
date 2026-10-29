"""Text and currency helpers shared by the console, Markdown, HTML and CSV renderers."""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Sequence

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
_SPACES = re.compile(r"[\t\n\r\u2028\u2029]+")
_BEYOND_ASCII = re.compile(r"[\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")
ELLIPSIS = "\u2026"

CURRENCY_SYMBOLS: Dict[str, str] = {
    "GBP": "\u00a3",
    "USD": "$",
    "EUR": "\u20ac",
}

_ANSI = {
    "ok": "32",
    "warn": "33",
    "bad": "31",
    "dim": "2",
    "bold": "1",
    "head": "1;35",
    "accent": "35",
}


def clean_text(value: object) -> str:
    """Make a value safe to print: no control characters or bidirectional overrides."""
    text = "" if value is None else str(value)
    return _CONTROL.sub("", _SPACES.sub(" ", text)).strip()


def escape_invisible(json_text: str) -> str:
    """Spell characters that clean_text strips as \\uXXXX escapes in serialised JSON."""
    return _BEYOND_ASCII.sub(lambda match: "\\u%04x" % ord(match.group()), json_text)


def currency_symbol(currency: str) -> str:
    code = (currency or "GBP").strip().upper()
    return CURRENCY_SYMBOLS.get(code, f"{code} ")


def format_money(amount: Optional[float], currency: str = "GBP", *, signed: bool = False) -> str:
    """Format a monetary amount with two decimal places, or 'n/a' when missing."""
    if amount is None:
        return "n/a"
    symbol = currency_symbol(currency)
    if signed:
        sign = "+" if amount > 0 else ("-" if amount < 0 else "")
        return f"{sign}{symbol}{abs(amount):,.2f}"
    if amount < 0:
        return f"-{symbol}{abs(amount):,.2f}"
    return f"{symbol}{amount:,.2f}"


def format_hourly(amount: Optional[float], currency: str = "GBP") -> str:
    """Format an hourly rate with four decimal places, or 'n/a' when missing."""
    if amount is None:
        return "n/a"
    symbol = currency_symbol(currency)
    return f"{symbol}{amount:,.4f}"


def format_pct(pct: Optional[float], *, signed: bool = True) -> str:
    """Format a percentage change (for example +25.0% or +0.0%)."""
    if pct is None:
        return "n/a"
    whole = abs(pct - round(pct)) < 1e-6
    digits = f"{abs(pct):.0f}%" if whole else f"{abs(pct):.1f}%"
    if signed:
        prefix = "+" if pct > 0 else ("-" if pct < 0 else "+")
        return f"{prefix}{digits}"
    return f"-{digits}" if pct < 0 else digits


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else (0 if unicodedata.combining(ch) else 1)
               for ch in text)


def truncate(text: str, width: int) -> str:
    """Shorten to ``width`` columns, ending with an ellipsis when something was cut."""
    if display_width(text) <= width:
        return text
    if width <= 1:
        return ELLIPSIS[:width]
    out, used = [], 0
    for ch in text:
        step = display_width(ch)
        if used + step > width - 1:
            break
        out.append(ch)
        used += step
    return "".join(out).rstrip() + ELLIPSIS


def pad(text: str, width: int, align: str = "l") -> str:
    gap = max(0, width - display_width(text))
    return " " * gap + text if align == "r" else text + " " * gap


class Palette:
    """Applies ANSI styles only when colour is enabled."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def paint(self, text: str, style: Optional[str]) -> str:
        code = _ANSI.get(style or "")
        if not self.enabled or not code or not text:
            return text
        return f"\x1b[{code}m{text}\x1b[0m"


def fit_widths(natural: Sequence[int], flexible: Sequence[bool], limit: Optional[int], gap: int,
               floor: int = 8) -> List[int]:
    """Shrink flexible columns (widest first) until the table fits ``limit`` columns."""
    widths = list(natural)
    if limit is None:
        return widths
    budget = limit - gap * (len(widths) - 1)
    while sum(widths) > budget:
        candidates = [i for i, w in enumerate(widths) if flexible[i] and w > floor]
        if not candidates:
            break
        widest = max(candidates, key=lambda i: widths[i])
        widths[widest] -= 1
    return widths


def render_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    aligns: Optional[Sequence[str]] = None,
    flexible: Optional[Sequence[bool]] = None,
    styles: Optional[Sequence[Sequence[Optional[str]]]] = None,
    width: Optional[int] = None,
    indent: str = "  ",
    palette: Optional[Palette] = None,
    gap: int = 2,
    compact_headers: Optional[Sequence[str]] = None,
) -> List[str]:
    """Plain-text table with a rule under the header; widths are computed before colouring."""
    palette = palette or Palette(False)
    count = len(headers)
    aligns = list(aligns or ["l"] * count)
    flexible = list(flexible or [False] * count)
    cleaned = [[clean_text(cell) for cell in row] for row in rows]
    limit = None if width is None else max(20, width - len(indent))

    def measure(labels: Sequence[str]):
        parts = [label.split("\n") for label in labels]
        natural = [
            max([max(display_width(part) for part in parts[i])] + [display_width(row[i]) for row in cleaned])
            for i in range(count)
        ]
        return parts, natural

    header_parts, natural = measure(headers)
    if compact_headers is not None and limit is not None and sum(natural) + gap * (count - 1) > limit:
        header_parts, natural = measure(compact_headers)
    widths = fit_widths(natural, flexible, limit, gap)
    spacer = " " * gap

    def line(cells: Sequence[str], cell_styles: Optional[Sequence[Optional[str]]], header: bool = False) -> str:
        parts = []
        for i, cell in enumerate(cells):
            text = pad(truncate(cell, widths[i]), widths[i], aligns[i])
            style = "head" if header else (cell_styles[i] if cell_styles else None)
            parts.append(palette.paint(text, style))
        return (indent + spacer.join(parts)).rstrip() if not palette.enabled else indent + spacer.join(parts)

    depth = max(len(parts) for parts in header_parts)
    out = []
    for level in range(depth):
        cells = [parts[level - (depth - len(parts))] if level >= depth - len(parts) else "" for parts in header_parts]
        out.append(line(cells, None, header=True))
    out.append(indent + palette.paint(spacer.join("\u2500" * w for w in widths), "dim"))
    for index, row in enumerate(cleaned):
        out.append(line(row, styles[index] if styles else None))
    return out


def markdown_escape(value: object) -> str:
    """Escape a value for use inside a GitHub-flavoured Markdown table cell."""
    text = clean_text(value)
    for char in ("\\", "|", "`", "*", "<", ">", "[", "]"):
        text = text.replace(char, "\\" + char)
    return text


def plural(count: int, singular: str, plural_form: Optional[str] = None) -> str:
    return f"{count} {singular if count == 1 else (plural_form or singular + 's')}"
