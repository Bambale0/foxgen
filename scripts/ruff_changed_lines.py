"""Run Ruff on changed files but fail only for diagnostics touching new lines.

Legacy modules in this repository contain historical lint debt. The normal
review gate must still reject new violations without forcing an unrelated
full-file cleanup in every small pull request.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HUNK_RE = re.compile(
    r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@"
)
_DEFAULT_IGNORES = "E402,F403,F405,E501"


@dataclass(frozen=True, order=True)
class LineRange:
    start: int
    end: int

    def intersects(self, other: LineRange) -> bool:
        return self.start <= other.end and other.start <= self.end


def parse_added_ranges(diff_text: str) -> tuple[LineRange, ...]:
    """Extract added/modified head-side line ranges from a zero-context diff."""
    ranges: list[LineRange] = []
    for line in diff_text.splitlines():
        match = _HUNK_RE.match(line)
        if not match:
            continue
        start = int(match.group("start"))
        count = int(match.group("count") or "1")
        if count <= 0:
            continue
        ranges.append(LineRange(start=start, end=start + count - 1))
    return tuple(ranges)


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        check=check,
        text=True,
        capture_output=True,
    )


def added_ranges_for_file(
    *,
    repository: Path,
    base: str,
    head: str,
    filename: str,
) -> tuple[LineRange, ...]:
    result = _run(
        (
            "git",
            "diff",
            "--unified=0",
            "--no-color",
            "--find-renames",
            base,
            head,
            "--",
            filename,
        ),
        cwd=repository,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git diff failed for {filename}: {result.stderr.strip() or result.stdout.strip()}"
        )
    return parse_added_ranges(result.stdout)


def _location_range(payload: Any) -> LineRange | None:
    if not isinstance(payload, dict):
        return None
    try:
        start = int(payload["row"])
    except (KeyError, TypeError, ValueError):
        return None
    return LineRange(start=start, end=start)


def _span_range(start_payload: Any, end_payload: Any) -> LineRange | None:
    start = _location_range(start_payload)
    if start is None:
        return None
    end = _location_range(end_payload)
    return LineRange(start=start.start, end=(end.end if end else start.end))


def diagnostic_ranges(diagnostic: dict[str, Any]) -> tuple[LineRange, ...]:
    """Return both reported and auto-fix spans for one Ruff diagnostic."""
    ranges: list[LineRange] = []
    reported = _span_range(
        diagnostic.get("location"),
        diagnostic.get("end_location"),
    )
    if reported is not None:
        ranges.append(reported)

    fix = diagnostic.get("fix")
    edits = fix.get("edits") if isinstance(fix, dict) else None
    if isinstance(edits, list):
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            span = _span_range(edit.get("location"), edit.get("end_location"))
            if span is not None:
                ranges.append(span)
    return tuple(ranges)


def diagnostic_touches_changes(
    diagnostic: dict[str, Any],
    changed_ranges: Iterable[LineRange],
) -> bool:
    changed = tuple(changed_ranges)
    if not changed:
        return False
    return any(
        diagnostic_range.intersects(changed_range)
        for diagnostic_range in diagnostic_ranges(diagnostic)
        for changed_range in changed
    )


def _normalized_filename(repository: Path, raw_filename: str) -> str:
    path = Path(raw_filename)
    if path.is_absolute():
        try:
            path = path.resolve().relative_to(repository.resolve())
        except ValueError:
            return path.as_posix()
    return path.as_posix()


def filter_diagnostics(
    diagnostics: Iterable[dict[str, Any]],
    *,
    repository: Path,
    ranges_by_file: dict[str, tuple[LineRange, ...]],
) -> list[dict[str, Any]]:
    relevant: list[dict[str, Any]] = []
    for diagnostic in diagnostics:
        filename = _normalized_filename(
            repository,
            str(diagnostic.get("filename") or ""),
        )
        if diagnostic_touches_changes(
            diagnostic,
            ranges_by_file.get(filename, ()),
        ):
            relevant.append(diagnostic)
    return relevant


def _format_diagnostic(repository: Path, diagnostic: dict[str, Any]) -> str:
    filename = _normalized_filename(
        repository,
        str(diagnostic.get("filename") or "unknown"),
    )
    location = diagnostic.get("location") or {}
    row = location.get("row", 1)
    column = location.get("column", 1)
    code = diagnostic.get("code") or "RUF"
    message = diagnostic.get("message") or "Ruff diagnostic"
    return f"{filename}:{row}:{column}: {code} {message}"


def run_ruff(
    *,
    repository: Path,
    filenames: Sequence[str],
) -> list[dict[str, Any]]:
    command = [
        "ruff",
        "check",
        *filenames,
        f"--ignore={_DEFAULT_IGNORES}",
        "--output-format=json",
    ]
    result = _run(command, cwd=repository)
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Ruff returned invalid JSON: "
            f"{result.stderr.strip() or result.stdout[:500].strip()}"
        ) from exc
    if not isinstance(payload, list):
        raise TypeError("Ruff JSON output must be a list")
    if result.returncode not in {0, 1}:
        raise RuntimeError(
            f"Ruff execution failed: {result.stderr.strip() or result.stdout[:500].strip()}"
        )
    return [item for item in payload if isinstance(item, dict)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("files", nargs="+")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repository = Path.cwd()
    filenames = [Path(item).as_posix() for item in args.files]

    try:
        ranges_by_file = {
            filename: added_ranges_for_file(
                repository=repository,
                base=args.base,
                head=args.head,
                filename=filename,
            )
            for filename in filenames
        }
        diagnostics = run_ruff(repository=repository, filenames=filenames)
        relevant = filter_diagnostics(
            diagnostics,
            repository=repository,
            ranges_by_file=ranges_by_file,
        )
    except RuntimeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2

    for diagnostic in relevant:
        print(_format_diagnostic(repository, diagnostic))

    ignored_count = len(diagnostics) - len(relevant)
    print(
        "Ruff changed-line gate: "
        f"relevant={len(relevant)} ignored_legacy={ignored_count} files={len(filenames)}"
    )
    return 1 if relevant else 0


if __name__ == "__main__":
    raise SystemExit(main())
