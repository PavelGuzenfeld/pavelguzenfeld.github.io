#!/usr/bin/env python3
"""LLM-driven audio pronunciation enrichment for a Hugo post.

Reads a `.md` file, asks Claude to produce a YAML pronunciation map for
terms that would not survive literal text-to-speech (acronyms specific to
the post's domain, code-like identifiers, in-line jargon), and writes the
result into the post's frontmatter under `audio.pronunciation`.

Usage:
    enrich_audio_metadata.py <post.md> [--model claude-sonnet-4-5]
                                       [--write|--print]

Requires `ANTHROPIC_API_KEY` in the environment.

Layered with the static rules in `generate_audio.py`:
- Built-in PRONUNCIATION_RULES handle the universal stuff (compiler flags,
  SI units, common acronyms).  They cover ~80% of every post.
- This script fills in the long tail: project-specific names, novel
  abbreviations, proper-noun reading hints.  Run it once per post; the
  result is checked in alongside the post.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
from pathlib import Path

import yaml

try:
    import anthropic
except ImportError:
    print("This script needs the anthropic SDK: pip install anthropic", file=sys.stderr)
    raise


SYSTEM_PROMPT = textwrap.dedent("""\
    You are an audio-narration metadata generator for technical blog posts.
    The narrator reads the post text aloud (Microsoft Edge TTS).  Your job
    is to find terms in the post that would NOT be understandable when read
    literally — and produce a pronunciation map a listener can follow
    without seeing the text.

    Rules:
    - Expand acronyms specific to the post's domain.  Decide based on
      context whether to expand to a full phrase or letter-spell — letter-
      spelling reads natural for proper nouns ("the LMAX Disruptor"),
      expansion is better for technical jargon ("HFT" → "high-frequency
      trading").
    - For UPPER_SNAKE_CASE identifiers, prefer lowercase-with-spaces so the
      listener hears words, not letters.
    - For symbol-heavy code-like fragments, write what the speaker would
      naturally say (`<atomic>` → "the atomic header"; `std::vector<int>`
      → "vector of int").
    - Skip terms that already read fine literally — only include entries
      you'd correct if narrating yourself.
    - Skip terms covered by these built-in rules (don't duplicate):
        * compiler flags (-O2, -march=native, -ffast-math, -std=c++23)
        * SI units (ns/op, GHz, MiB, etc.)
        * universal acronyms (CRTP, HFT, SIMD, AVX, AVX2, AVX-512, SSE,
          AoS, SoA, GCC, LLVM, MSVC, STL, SSO, IEEE, ABI, MPMC, SPSC,
          BTB, NRVO, PGO, FMA, MMU, TLB, CAS, UB, L1d, L1i, L2, L3)
        * preprocessor directives (#define, #include, #ifdef, etc.)
        * UPPER_SNAKE identifiers (already converted to lowercase words)
        * GCC builtins (__builtin_X already becomes "the X built-in")

    Output a STRICT JSON object (no markdown fences, no commentary) of the
    form `{"shown": "narrated", ...}`.  Empty object `{}` is acceptable
    when the built-in rules cover everything.
    """)


FRONTMATTER_RE = re.compile(r"^(---\n)(.*?)(\n---\n)", re.DOTALL)


def read_post(path: Path) -> tuple[dict, str, str]:
    """Return (frontmatter_dict, raw_yaml, body)."""
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise SystemExit(f"{path}: no YAML frontmatter found")
    fm = yaml.safe_load(m.group(2)) or {}
    body = text[m.end():]
    return fm, m.group(2), body


def write_post(path: Path, fm: dict, body: str) -> None:
    fm_yaml = yaml.safe_dump(
        fm, sort_keys=False, allow_unicode=True, default_flow_style=False
    ).rstrip()
    path.write_text(f"---\n{fm_yaml}\n---\n{body}", encoding="utf-8")


def ask_claude(model: str, post_path: Path, post_text: str) -> dict[str, str]:
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Post: {post_path.name}\n\n"
                    "Markdown source follows.  Return only the JSON map.\n\n"
                    "<post>\n" + post_text + "\n</post>"
                ),
            }
        ],
    )
    raw = "".join(b.text for b in message.content if b.type == "text").strip()
    # Strip accidental markdown fences.
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("post", type=Path)
    ap.add_argument("--model", default="claude-sonnet-4-5",
                    help="Anthropic model (default: claude-sonnet-4-5)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true",
                   help="merge the result into the post's frontmatter (default)")
    g.add_argument("--print", action="store_true",
                   help="just print the JSON, don't write")
    args = ap.parse_args()

    if "ANTHROPIC_API_KEY" not in os.environ:
        print("ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 1

    fm, _, body = read_post(args.post)
    text = args.post.read_text(encoding="utf-8")

    pron = ask_claude(args.model, args.post, text)

    if args.print or not args.write:
        print(json.dumps(pron, indent=2, ensure_ascii=False))
        if args.print:
            return 0

    audio = fm.setdefault("audio", {})
    existing = audio.setdefault("pronunciation", {}) or {}
    # New entries from the LLM win when the key is novel; existing entries
    # the human edited stay put.
    for k, v in pron.items():
        if k not in existing:
            existing[k] = v
    audio["pronunciation"] = existing

    write_post(args.post, fm, body)
    print(f"merged {len(pron)} entries into {args.post}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
