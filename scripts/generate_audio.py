#!/usr/bin/env python3
"""Generate an MP3 narration of a Hugo blog post via Microsoft Edge TTS.

Usage:
    generate_audio.py <post.md> <output.mp3> [--voice VOICE] [--rate RATE]

Pipeline: markdown → cleaned text → edge-tts (Microsoft Neural voice) → MP3.

Three layers of pronunciation control:

1. Built-in PRONUNCIATION_RULES below — global defaults for compiler flags,
   SI units, common acronyms.  Apply to every post.

2. Per-post frontmatter overrides under `audio.pronunciation`:

       ---
       title: "..."
       audio:
         pronunciation:
           ns/op: nanoseconds per operation
           L1d:   L one D cache
       ---

   These take precedence over the built-ins for that one post.

3. Inline overrides via the Hugo shortcode `{{< pron "shown" "narrated" >}}`
   (or the markdown-flavoured fallback `[[shown|narrated]]`).  The HTML
   renderer shows only "shown"; the audio script substitutes "narrated".
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

import edge_tts
import yaml


# ---------- markdown → narration text ----------------------------------------

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
FENCED_CODE_RE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)
INDENTED_CODE_RE = re.compile(r"(?:^    .*\n)+", re.MULTILINE)
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
TABLE_RE = re.compile(r"(?:^\|.*\|\s*\n)+", re.MULTILINE)
IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
# Link text that *itself* looks like a URL — drop the whole link.  Otherwise
# the narrator reads "godbolt dot org slash Z slash 8 Z E Q O J A F G".
LINK_TEXT_IS_URL_RE = re.compile(
    r"^\s*(?:https?://|www\.|[\w-]+\.[a-z]{2,}(?:/|$))",
    re.IGNORECASE,
)
BARE_URL_RE = re.compile(r"https?://\S+")
HTML_TAG_RE = re.compile(r"</?[a-z][a-z0-9]*(?:\s[^>]*)?>", re.IGNORECASE)
NAMESPACE_NOISE_RE = re.compile(r"\b\w+::")
# Asterisk-only — `_..._` and `__...__` get eaten across word boundaries
# (e.g. ANKERL_NANOBENCH_IMPLEMENT becomes ANKERLNANOBENCHIMPLEMENT).
# Writers using `_italic_` should switch to `*italic*` if they want it stripped.
EMPHASIS_RE = re.compile(r"(\*\*|\*)(.+?)\1")

# Inline pronunciation overrides — see Layer 3 in the module docstring.
PRON_SHORTCODE_RE = re.compile(
    r'\{\{<\s*pron\s+"(?P<shown>[^"]+)"\s+"(?P<narrated>[^"]+)"\s*>\}\}'
)
PRON_BRACKETS_RE = re.compile(r"\[\[(?P<shown>[^\]|]+)\|(?P<narrated>[^\]]+)\]\]")


# ---------- Layer 1: built-in global pronunciation rules ---------------------

PRONUNCIATION_RULES: list[tuple[re.Pattern[str], object]] = [
    # Combo "-O2 -std=c++23" → "O2 optimization on C plus plus 23 standard"
    (re.compile(r"-O(\d|fast|s|g)\s+-std=c\+\+(\d+)", re.IGNORECASE),
     r"O\1 optimization on C plus plus \2 standard"),

    # `-std=c++NN` alone
    (re.compile(r"-std=c\+\+(\d+)", re.IGNORECASE),
     r"C plus plus \1 standard"),

    # Compiler optimization levels
    (re.compile(r"-Ofast\b"),  "O fast optimization"),
    (re.compile(r"-Os\b"),     "O size optimization"),
    (re.compile(r"-Og\b"),     "O g debug optimization"),
    (re.compile(r"-O(\d)\b"),  r"O\1 optimization"),

    # Flag families
    (re.compile(r"-march=x86-64-v(\d)\b"), r"march x86-64 version \1"),
    (re.compile(r"-march=native\b"),       "march native"),
    (re.compile(r"-march=([\w.-]+)"),      r"march \1"),
    (re.compile(r"-ffast-math\b"),         "fast math"),
    (re.compile(r"-flto\b"),               "link time optimization"),
    (re.compile(r"-fno-exceptions\b"),     "no exceptions"),
    (re.compile(r"-fno-rtti\b"),           "no R T T I"),
    (re.compile(r"-fno-plt\b"),            "no P L T"),
    (re.compile(r"-Wall\b"),               "W all"),
    (re.compile(r"-Wextra\b"),             "W extra"),
    (re.compile(r"-Werror\b"),             "warnings as errors"),
    (re.compile(r"-W(\w[\w-]+)"),          r"W \1 warning"),

    # `c++NN` and bare `C++` — must run AFTER -std=c++ rule.
    (re.compile(r"\bC\+\+(\d+)\b", re.IGNORECASE),  r"C plus plus \1"),
    (re.compile(r"\bC\+\+", re.IGNORECASE),         "C plus plus"),

    # GCC builtins: `__builtin_popcountll` → "the popcountll built-in"
    (re.compile(r"\b__builtin_(\w+)"),  r"the \1 built-in"),

    # `g++` mirror of the C++ rule
    (re.compile(r"\bg\+\+\b"),  "g plus plus"),

    # Preprocessor directives — rule: read so a listener understands without
    # seeing the source.  "hash define" is jargon the listener won't recognize
    # if they haven't read the post first; "define X" just works.
    (re.compile(r"#defines?\s+(\w+)"),                  r"define the \1 macro"),
    (re.compile(r"#includes?\s*<([\w./-]+)\.h>"),       r"include the \1 header"),
    (re.compile(r"#includes?\s*<([\w./-]+)>"),          r"include the \1 header"),
    (re.compile(r"#includes?\s*\"([\w./-]+)\.h\""),     r"include the \1 header"),
    (re.compile(r"#includes?\s*\"([\w./-]+)\""),        r"include the \1 header"),
    (re.compile(r"#ifdef\s+(\w+)"),                     r"if \1 is defined"),
    (re.compile(r"#ifndef\s+(\w+)"),                    r"if \1 is not defined"),
    (re.compile(r"#endif\b"),                           "end if"),
    (re.compile(r"#pragma\s+(\w+)"),                    r"the \1 pragma"),

    # UPPER_SNAKE_CASE identifiers (≥ 2 underscored segments) read as words.
    # Must run AFTER preprocessor rules — those capture identifiers via \w+
    # which would otherwise stop at the spaces this rule introduces.
    (re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z][A-Z0-9]*)+)\b"),
     lambda m: m.group(1).replace("_", " ").lower()),

    # Units
    (re.compile(r"\bns/(?:op|ops|iter|iteration)\b"),  "nanoseconds per operation"),
    (re.compile(r"\b([0-9.]+)\s*ns\b"),               r"\1 nanoseconds"),
    (re.compile(r"\b([0-9.]+)\s*µs\b"),               r"\1 microseconds"),
    (re.compile(r"\b([0-9.]+)\s*ms\b"),               r"\1 milliseconds"),
    (re.compile(r"\b([0-9.]+)\s*GB/s\b"),             r"\1 gigabytes per second"),
    (re.compile(r"\b([0-9.]+)\s*MB/s\b"),             r"\1 megabytes per second"),
    (re.compile(r"\b([0-9.]+)\s*GHz\b"),              r"\1 gigahertz"),
    (re.compile(r"\b([0-9.]+)\s*MHz\b"),              r"\1 megahertz"),
    (re.compile(r"\b([0-9.]+)\s*KiB\b"),              r"\1 kilobytes"),
    (re.compile(r"\b([0-9.]+)\s*MiB\b"),              r"\1 megabytes"),
    (re.compile(r"\b([0-9.]+)\s*GiB\b"),              r"\1 gigabytes"),

    # "2x" / "3.6x" / "70×"
    (re.compile(r"\b([0-9.]+)\s*[x×]\b"),  r"\1 times"),

    # Acronyms — rule: expand to the full phrase so a listener understands
    # without seeing the text.  Per-post frontmatter can override these for
    # context where the letter-spelling actually reads better (e.g. proper
    # nouns like "the LMAX Disruptor").
    (re.compile(r"\bSIMD\b"),       "single instruction multiple data"),
    (re.compile(r"\bAVX-512\b"),    "advanced vector extensions five twelve"),
    (re.compile(r"\bAVX2\b"),       "advanced vector extensions two"),
    (re.compile(r"\bAVX\b"),        "advanced vector extensions"),
    (re.compile(r"\bSSE2\b"),       "streaming SIMD extensions two"),
    (re.compile(r"\bSSE\b"),        "streaming SIMD extensions"),
    (re.compile(r"\bL1d\b"),        "L1 data cache"),
    (re.compile(r"\bL1i\b"),        "L1 instruction cache"),
    (re.compile(r"\bL([123])\b"),   r"L\1 cache"),
    (re.compile(r"\bCRTP\b"),       "curiously recurring template pattern"),
    (re.compile(r"\bAoS\b"),        "array of structs"),
    (re.compile(r"\bSoA\b"),        "struct of arrays"),
    (re.compile(r"\bHFT\b"),        "high-frequency trading"),
    (re.compile(r"\bGCC\b"),        "GCC"),     # spoken as one word
    (re.compile(r"\bLLVM\b"),       "LLVM"),    # name, leave as is
    (re.compile(r"\bLTO\b"),        "link-time optimization"),
    (re.compile(r"\bMSVC\b"),       "Microsoft Visual C plus plus"),
    (re.compile(r"\bSTL\b"),        "standard template library"),
    (re.compile(r"\bSSO\b"),        "small-string optimization"),
    (re.compile(r"\bIEEE-754\b"),   "I triple E 754"),
    (re.compile(r"\bIEEE\b"),       "I triple E"),
    (re.compile(r"\bABI\b"),        "application binary interface"),
    (re.compile(r"\bAPI\b"),        "API"),
    (re.compile(r"\bMPMC\b"),       "multi-producer multi-consumer"),
    (re.compile(r"\bSPSC\b"),       "single-producer single-consumer"),
    (re.compile(r"\bBTB\b"),        "branch target buffer"),
    (re.compile(r"\bDRAM\b"),       "DRAM"),
    (re.compile(r"\bNRVO\b"),       "named return value optimization"),
    (re.compile(r"\bPGO\b"),        "profile-guided optimization"),
    (re.compile(r"\bFMA\b"),        "fused multiply-add"),
    (re.compile(r"\bSDK\b"),        "SDK"),
    (re.compile(r"\bMMU\b"),        "memory management unit"),
    (re.compile(r"\bTLB\b"),        "translation lookaside buffer"),
    (re.compile(r"\bCAS\b"),        "compare-and-swap"),
    (re.compile(r"\bUB\b"),         "undefined behaviour"),
    (re.compile(r"\bI/O\b"),        "I O"),
]


def apply_global_rules(text: str) -> str:
    for pat, repl in PRONUNCIATION_RULES:
        text = pat.sub(repl, text)  # type: ignore[arg-type]
    return text


# ---------- Layer 2: per-post frontmatter pronunciation overrides ------------

def parse_frontmatter(md: str) -> dict:
    m = FRONTMATTER_RE.match(md)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}


def apply_frontmatter_rules(text: str, frontmatter: dict) -> str:
    audio_cfg = frontmatter.get("audio") or {}
    pron = audio_cfg.get("pronunciation") or {}
    # Sort keys longest-first so longer phrases match before their substrings.
    for shown in sorted(pron, key=len, reverse=True):
        narrated = pron[shown]
        text = re.sub(re.escape(str(shown)), str(narrated), text)
    return text


# ---------- Layer 3: inline shortcode / [[shown|narrated]] -------------------

def apply_inline_overrides(text: str) -> str:
    text = PRON_SHORTCODE_RE.sub(lambda m: m.group("narrated"), text)
    text = PRON_BRACKETS_RE.sub(lambda m: m.group("narrated"), text)
    return text


def _link_replacer(m: re.Match[str]) -> str:
    """Keep meaningful link text; drop links whose text is a URL/short slug."""
    text = m.group(1)
    if LINK_TEXT_IS_URL_RE.match(text):
        return ""
    return text


# ---------- main cleaner -----------------------------------------------------

def clean_markdown(md: str) -> str:
    frontmatter = parse_frontmatter(md)
    body = FRONTMATTER_RE.sub("", md, count=1)

    # Layer 3 first — these are intentional, the writer asked for them.
    body = apply_inline_overrides(body)

    # Drop code blocks before any other rule sees their contents.
    body = FENCED_CODE_RE.sub("\n[code block omitted]\n", body)
    body = INDENTED_CODE_RE.sub("\n[code block omitted]\n", body)
    body = TABLE_RE.sub("\n[table omitted]\n", body)

    body = IMAGE_RE.sub("", body)
    body = LINK_RE.sub(_link_replacer, body)
    body = BARE_URL_RE.sub("", body)
    body = HTML_TAG_RE.sub("", body)
    body = NAMESPACE_NOISE_RE.sub("", body)
    body = EMPHASIS_RE.sub(r"\2", body)
    body = INLINE_CODE_RE.sub(r"\1", body)

    # Headers → "Section: title"
    out_lines: list[str] = []
    for line in body.splitlines():
        h = re.match(r"^(#{1,6})\s+(.*)", line)
        if h:
            out_lines.append(f"Section: {h.group(2).strip()}.")
        else:
            out_lines.append(line)
    body = "\n".join(out_lines)

    # Layer 2 then Layer 1 — frontmatter takes precedence over the built-ins.
    body = apply_frontmatter_rules(body, frontmatter)
    body = apply_global_rules(body)

    # Drop orphaned label lines like "Godbolt:" left behind once their link
    # was stripped — a label with nothing after it reads as filler.
    body = re.sub(r"^\s*[\w][\w ]{0,30}:\s*$", "", body, flags=re.MULTILINE)

    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body


# ---------- edge-tts ---------------------------------------------------------

async def synthesize(text: str, voice: str, rate: str, out_mp3: Path) -> None:
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
    await communicate.save(str(out_mp3))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path, help="path to a Hugo post .md")
    ap.add_argument("output", type=Path, help="path to write the MP3")
    ap.add_argument(
        "--voice",
        # English-only Andrew — the "Multilingual" sibling slips into German
        # on words like "Müller" mid-sentence.
        default="en-US-AndrewNeural",
        help="edge-tts voice id (try en-US-GuyNeural, en-US-ChristopherNeural, "
             "en-US-EricNeural, en-US-BrianNeural; avoid Multilingual variants "
             "for English-only posts)",
    )
    ap.add_argument(
        "--rate",
        default="+0%",
        help="speaking rate offset, e.g. '+10%%' or '-5%%'",
    )
    ap.add_argument(
        "--text-only",
        action="store_true",
        help="just print the cleaned text, don't synthesize",
    )
    args = ap.parse_args()

    md = args.input.read_text(encoding="utf-8")
    text = clean_markdown(md)

    if args.text_only:
        sys.stdout.write(text)
        return 0

    asyncio.run(synthesize(text, args.voice, args.rate, args.output))
    print(f"wrote {args.output} ({args.output.stat().st_size:,} bytes) "
          f"voice={args.voice}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
