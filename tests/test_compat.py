"""Verify Python 3.9+ compatibility across every source file."""

from __future__ import annotations

import io
import tokenize
import unittest
from pathlib import Path
from typing import Dict, Iterator, List

REPO = Path(__file__).resolve().parent.parent
PREFIX_LETTERS = "fFrRbBuU"
HAS_FSTRING_TOKENS = hasattr(tokenize, "FSTRING_START")


def source_files() -> Iterator[Path]:
    yield REPO / "azure-legacy-vm-report"
    for folder in ("azure_legacy_vm_report", "tests"):
        yield from sorted((REPO / folder).rglob("*.py"))


def fstring_problems(source: str) -> List[str]:
    problems: List[str] = []
    delimiters: List[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        line = token.start[0]
        if token.type == tokenize.FSTRING_START:
            quote = token.string.lstrip(PREFIX_LETTERS)
            if any(quote.startswith(outer) for outer in delimiters):
                problems.append(f"line {line}: an f-string that reuses the quotes of the f-string around it")
            delimiters.append(quote)
        elif token.type == tokenize.FSTRING_END:
            delimiters.pop()
        elif not delimiters:
            continue
        elif token.type == tokenize.FSTRING_MIDDLE:
            if len(delimiters) > 1 and "\\" in token.string:
                problems.append(f"line {line}: a backslash inside a replacement field")
        elif token.type == tokenize.STRING:
            if "\\" in token.string:
                problems.append(f"line {line}: a backslash inside a replacement field")
            if any(token.string.lstrip(PREFIX_LETTERS).startswith(outer) for outer in delimiters):
                problems.append(f"line {line}: a string that reuses the quotes of the f-string around it")
        elif token.type == tokenize.COMMENT:
            problems.append(f"line {line}: a comment inside a replacement field")
        elif token.type == tokenize.NL and len(delimiters[-1]) == 1:
            problems.append(f"line {line}: a replacement field that spans lines in a single-quoted f-string")
    return problems


class CompatibilityTests(unittest.TestCase):
    def test_every_file_compiles(self) -> None:
        files = list(source_files())
        self.assertGreaterEqual(len(files), 15)
        for path in files:
            with self.subTest(path=path.name):
                compile(path.read_text(encoding="utf-8"), str(path), "exec")

    @unittest.skipUnless(HAS_FSTRING_TOKENS, "Python <3.12 rejects PEP 701 f-strings during compile()")
    def test_no_f_string_relies_on_python_3_12(self) -> None:
        found: Dict[str, List[str]] = {}
        for path in source_files():
            problems = fstring_problems(path.read_text(encoding="utf-8"))
            if problems:
                found[path.name] = problems
        self.assertEqual(found, {})
