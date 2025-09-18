#!/usr/bin/env python3
"""
Build a normalized TSV of goods/services classifications.

Reads one or more input files and writes a UTF-8, tab-separated file with
exactly three columns per line: nice_class, item_name, group_code.

Usage examples:
  python build_goods_services_tsv.py --input raw.txt
  python build_goods_services_tsv.py -i a.tsv b.tsv --output app/data/goods_services/ko_goods_services.tsv

Input assumptions:
- Lines are either tab-separated or use 2+ spaces between the 3 fields.
- Blank lines are skipped. Leading/trailing whitespace is trimmed.
- The middle field (item_name) can contain spaces.

This script streams input and output to handle large files (~300k lines).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Tuple, TextIO


DEFAULT_OUTPUT = Path("app/data/goods_services/ko_goods_services.tsv")


def _iter_lines(lines: Iterable[str], source_name: str) -> Iterable[Tuple[int, str, str]]:
    """Yield parsed rows (nice_class, item_name, group_code) from a file.

    Supports either tab-separated or 2+ space-separated formats. Skips blank
    lines. Performs light validation and normalization.
    """

    splitter_multi_space = re.compile(r"\s{2,}")

    for lineno, raw in enumerate(lines, start=1):
            line = raw.strip()
            if not line:
                continue

            parts = line.split("\t")
            if len(parts) != 3:
                parts = splitter_multi_space.split(line)

            if len(parts) != 3:
                sys.stderr.write(f"[WARN] {source_name}:{lineno}: expected 3 columns, got {len(parts)}\n")
                continue

            nice_class_raw, item_name_raw, group_code_raw = parts

            # Normalize fields
            try:
                nice_class = int(str(nice_class_raw).strip())
            except Exception:
                sys.stderr.write(f"[WARN] {source_name}:{lineno}: invalid nice_class '{nice_class_raw}'\n")
                continue

            item_name = str(item_name_raw).strip()
            group_code = str(group_code_raw).strip()

            if not item_name:
                sys.stderr.write(f"[WARN] {source_name}:{lineno}: empty item_name\n")
                continue

            yield nice_class, item_name, group_code


def iter_rows(path: Path, encoding: str = "utf-8") -> Iterable[Tuple[int, str, str]]:
    with path.open("r", encoding=encoding, errors="replace") as f:
        yield from _iter_lines(f, str(path))


def ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def write_tsv(rows: Iterable[Tuple[int, str, str]], out_path: Path, append: bool = False) -> int:
    mode = "a" if append else "w"
    ensure_parent(out_path)
    written = 0
    with out_path.open(mode, encoding="utf-8", newline="") as w:
        for nice_class, item_name, group_code in rows:
            w.write(f"{nice_class}\t{item_name}\t{group_code}\n")
            written += 1
    return written


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build goods/services TSV")
    p.add_argument("-i", "--input", nargs="+", required=True, help="Input file(s) to read")
    p.add_argument("-o", "--output", default=str(DEFAULT_OUTPUT), help="Output TSV path")
    p.add_argument("--encoding", default="utf-8", help="Input encoding (default: utf-8)")
    p.add_argument("--append", action="store_true", help="Append to output instead of overwrite")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    out_path = Path(args.output)
    if not args.append and out_path.exists():
        # Overwrite confirmation is implicit; we simply overwrite to match request.
        pass

    total_in = 0
    total_out = 0

    for in_file in args.input:
        p = Path(in_file)
        # Support reading from STDIN via '-' pseudo-file
        if in_file == "-":
            rows = _iter_lines(sys.stdin, "<stdin>")
        else:
            if not p.exists():
                sys.stderr.write(f"[WARN] input not found: {p}\n")
                continue
            # Prevent reading and writing the same file simultaneously
            try:
                if p.resolve() == out_path.resolve():
                    sys.stderr.write(f"[WARN] skipping input identical to output: {p}\n")
                    continue
            except Exception:
                # On some filesystems resolve may fail; ignore and proceed
                pass
            rows = iter_rows(p, encoding=args.encoding)

        # Stream write per file; for append=False on first file we truncate, then append on subsequent files
        wrote = write_tsv(rows, out_path, append=(args.append or total_in > 0))
        total_in += 1
        total_out += wrote

    sys.stdout.write(f"Wrote {total_out} rows to {out_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
