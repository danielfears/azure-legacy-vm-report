"""Output formats: choosing them, writing report files safely and opening the HTML report."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Sequence

from .csvout import (
    render_json,
    render_skus_csv,
    render_subscriptions_csv,
    render_summary_csv,
    render_vms_csv,
)
from .htmlout import render_html
from .mdout import render_markdown
from .report import Report

FORMAT_CONSOLE = "console"
FORMAT_CSV = "csv"
FORMAT_JSON = "json"
FORMAT_MARKDOWN = "md"
FORMAT_HTML = "html"
ALL_FORMATS = (FORMAT_CONSOLE, FORMAT_CSV, FORMAT_JSON, FORMAT_MARKDOWN, FORMAT_HTML)
_ALIASES = {"markdown": FORMAT_MARKDOWN, "htm": FORMAT_HTML}
STEM_PREFIX = "azure-legacy-vm-report-"
_MAX_NAME_ATTEMPTS = 1000


def parse_formats(values: Sequence[str]) -> List[str]:
    """Turn repeated/comma-separated ``--format`` values into an ordered, de-duplicated list."""
    chosen = set()
    for value in values:
        for part in str(value).split(","):
            name = part.strip().lower()
            if not name:
                continue
            if name == "all":
                chosen.update(ALL_FORMATS)
                continue
            name = _ALIASES.get(name, name)
            if name not in ALL_FORMATS:
                raise ValueError(f"Unknown format {part.strip()!r}. Choose from {', '.join(ALL_FORMATS)} or all.")
            chosen.add(name)
    if not chosen:
        raise ValueError("No output format was given.")
    return [name for name in ALL_FORMATS if name in chosen]


@dataclass(frozen=True)
class OutputFile:
    format: str
    suffix: str
    content: bytes


def render_files(report: Report, formats: Sequence[str]) -> List[OutputFile]:
    """Render every file-based format (the console report is printed, not written)."""
    files: List[OutputFile] = []
    for name in formats:
        if name == FORMAT_CSV:
            for suffix, text in (
                ("-vms.csv", render_vms_csv(report)),
                ("-skus.csv", render_skus_csv(report)),
                ("-subscriptions.csv", render_subscriptions_csv(report)),
                ("-summary.csv", render_summary_csv(report)),
            ):
                files.append(OutputFile(name, suffix, text.encode("utf-8-sig")))
        elif name == FORMAT_JSON:
            files.append(OutputFile(name, ".json", render_json(report).encode("utf-8")))
        elif name == FORMAT_MARKDOWN:
            files.append(OutputFile(name, ".md", render_markdown(report).encode("utf-8")))
        elif name == FORMAT_HTML:
            files.append(OutputFile(name, ".html", render_html(report).encode("utf-8")))
    return files


def default_stem(report: Report) -> str:
    stamp = report.generated_at.astimezone(report.tz).strftime("%Y%m%d%H%M%S")
    return f"{STEM_PREFIX}{stamp}"


def prepare_directory(directory: Path) -> Path:
    """Create the output directory (private to the user when new) and check it is writable."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not os.access(directory, os.W_OK | os.X_OK):
        raise PermissionError(f"{directory} is not writable")
    return directory


def inside_git_repository(directory: Path) -> bool:
    """True when the directory sits inside a git working tree (reports hold tenant data)."""
    try:
        current = directory.resolve()
    except OSError:
        return False
    return any((candidate / ".git").exists() for candidate in (current, *current.parents))


def _free_stem(directory: Path, stem: str, suffixes: Sequence[str]) -> str:
    for attempt in range(1, _MAX_NAME_ATTEMPTS + 1):
        candidate = stem if attempt == 1 else f"{stem}-{attempt}"
        if not any(os.path.lexists(directory / f"{candidate}{suffix}") for suffix in suffixes):
            return candidate
    raise OSError(f"Could not find an unused file name starting with {stem} in {directory}")


def write_files(directory: Path, stem: str, files: Sequence[OutputFile]) -> List[Path]:
    """Write the files with owner-only permissions, never overwriting an existing report."""
    final = _free_stem(directory, stem, [item.suffix for item in files])
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    written: List[Path] = []
    for item in files:
        path = directory / f"{final}{item.suffix}"
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(item.content)
        written.append(path)
    return written


def open_in_browser(
    path: Path,
    *,
    env: Optional[Mapping[str, str]] = None,
    platform: Optional[str] = None,
    which: Callable[[str], Optional[str]] = shutil.which,
    run: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run,
) -> Optional[str]:
    """Open an HTML file in the user's browser; returns a warning string when it cannot."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    target = str(path.resolve())

    if env.get("WSL_DISTRO_NAME"):
        wslview = which("wslview")
        if wslview:
            res = run([wslview, target], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, check=False)
            if res.returncode == 0:
                return None
        wslpath = which("wslpath")
        explorer = which("explorer.exe")
        if wslpath and explorer:
            conv = run([wslpath, "-w", target], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL, text=True, check=False)
            win_path = (conv.stdout or "").strip()
            if conv.returncode == 0 and win_path:
                # explorer.exe commonly returns exit status 1 even on success.
                run([explorer, win_path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, check=False)
                return None
        return f"Could not open {target} automatically from WSL; open it in your browser."

    if platform == "darwin":
        opener = which("open")
        if opener:
            res = run([opener, target], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, check=False)
            if res.returncode == 0:
                return None
    elif platform.startswith("win"):
        startfile = getattr(os, "startfile", None)
        if startfile is not None:
            try:
                startfile(target)
                return None
            except OSError as exc:
                return f"Could not open {target} in a browser: {exc}"
    else:
        xdg = which("xdg-open")
        if xdg:
            res = run([xdg, target], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, check=False)
            if res.returncode == 0:
                return None
    return f"Could not open {target} in a browser automatically."
