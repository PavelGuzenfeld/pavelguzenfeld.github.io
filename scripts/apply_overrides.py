#!/usr/bin/env python3
"""Merge a PER_POST_OVERRIDES dict into each post's frontmatter.

Input: a text file containing a Python literal `PER_POST_OVERRIDES = {...}`.
Output: per-post `audio.pronunciation` blocks merged in place.

usage:
    apply_overrides.py /tmp/audio-overrides.txt content/posts/
"""
import ast
import re
import sys
from pathlib import Path

import yaml


FRONTMATTER_RE = re.compile(r"^(---\n)(.*?)(\n---\n)", re.DOTALL)


def extract_dict(blob: str) -> dict:
    m = re.search(r"PER_POST_OVERRIDES\s*=\s*(\{.*?\n\})", blob, re.DOTALL)
    if not m:
        raise SystemExit("can't find PER_POST_OVERRIDES = {...} in input")
    return ast.literal_eval(m.group(1))


def merge_into_post(path: Path, overrides: dict[str, str]) -> bool:
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        print(f"{path.name}: no frontmatter, skipping", file=sys.stderr)
        return False
    fm = yaml.safe_load(m.group(2)) or {}
    audio = fm.setdefault("audio", {})
    pron = audio.setdefault("pronunciation", {}) or {}
    added = 0
    for k, v in overrides.items():
        if k not in pron:
            pron[k] = v
            added += 1
    if not added:
        return False
    audio["pronunciation"] = pron
    fm["audio"] = audio
    new_yaml = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True,
                              default_flow_style=False).rstrip()
    path.write_text(f"---\n{new_yaml}\n---\n{text[m.end():]}",
                    encoding="utf-8")
    print(f"{path.name}: +{added} entries", file=sys.stderr)
    return True


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: apply_overrides.py <dict.txt> <posts-dir>")
    overrides_blob = Path(sys.argv[1]).read_text(encoding="utf-8")
    posts_dir = Path(sys.argv[2])
    table = extract_dict(overrides_blob)
    total = 0
    for post_filename, entries in table.items():
        path = posts_dir / post_filename
        if not path.exists():
            print(f"missing post: {post_filename}", file=sys.stderr)
            continue
        if merge_into_post(path, entries):
            total += 1
    print(f"updated {total} posts", file=sys.stderr)


if __name__ == "__main__":
    main()
