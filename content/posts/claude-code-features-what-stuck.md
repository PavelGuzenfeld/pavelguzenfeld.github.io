---
title: 'Claude Code Features I Had Not Tried: What Stuck, What Did Not'
date: 2026-10-31T01:00:00+03:00
draft: false
cover:
  image: /images/posts/claude-code-features-what-stuck.png
  alt: 'Claude Code features from an NDC Oslo 2026 talk, checked against seven months of my own usage'
tags:
- Claude Code
- AI
- developer-tools
- security
keywords:
- claude code tips
- claude code slash commands
- claude code permissions deny
- claude code context window
- claude code plan mode ctrl+g
- claude code rewind
- claude -p headless
- CLAUDE.md import
- NDC Oslo 2026 claude code
categories:
- deep-dive
summary: 'A talk at NDC Oslo 2026 walks through about 40 Claude Code features most
  people never use. I checked them against seven months of my own prompt history,
  ran the testable ones headless, and tried some interactive ones by hand. Ctrl+G and
  rewind stuck, /focus did not, and a permissions.deny rule on .env let a shell glob
  read the file anyway.'
ShowToc: true
audio:
  pronunciation:
    CLAUDE.md: Claude dot M D
    MCP: M C P
    /btw: slash B T W
    claude -p: claude dash P
    Ctrl+G: control G
    Ctrl+S: control S
---

Gui Ferreira gave a talk at NDC Oslo 2026, [What Claude Code Can Do That You Haven't Tried](https://www.youtube.com/watch?v=P3TCZ2xrvbo). His claim is that most people use 10 to 20 percent of the tool. He then walks through about 40 features in four groups: one-time setup, daily workflow, the platform layer, and non-coding use.

I use Claude Code every day, so I wanted to know which group I'm in. Instead of guessing, I measured. Claude Code keeps every prompt you type in `~/.claude/history.jsonl`. Mine goes back to March 2026 and has 18,312 entries. I counted how often each feature from the talk shows up, ran the ones that work headless in a scratch directory, and tried some of the interactive ones by hand.

Everything here is Claude Code 2.1.314.

## What the history says

Slash commands and inline keywords show up in the history. Keyboard shortcuts don't, so Shift+Tab, Ctrl+G, Ctrl+S and double-Esc are unmeasured, not unused.

| Feature | Uses since March |
|---|---|
| `/model` | 298 |
| `/usage` | 203 |
| `/clear` | 184 |
| `/goal` | 73 |
| `!` bash prefix | 56 |
| `/simplify` | 31 |
| `/rename` | 25 |
| `/plan` | 24 |
| `/context` | 14 |
| `/compact` | 14 |
| `/btw` | 10 |
| `@file` mention | 10 |
| `/effort` | 5 |
| `/status` | 4 |
| `/agents` | 3 |
| `/insights` | 1 |
| `/diff` | 1 |
| `ultrathink` | 0 |
| `/batch`, `/loop`, `/memory`, `/import`, `/doctor`, `/statusline`, `/voice`, `/color`, `/focus` | 0 |

Two things stand out.

First, the commands I use most aren't in the talk at all. `/goon` (770), `/done` (289), `/kata` (126) and `/grill-me` plus `/grill` (192) are skills from my own pack, [agent-sdlc](https://github.com/PavelGuzenfeld/agent-sdlc). The talk's "interview me" tip is exactly what `/grill` does. It asks one question at a time until nothing in the design is left open. I typed "interview me" once. I typed `/grill` 192 times. Once a prompt pattern works, it should become a skill. The talk makes the same point near the end.

Second, `/model` at 298 is a lot. The talk's advice to pick the model and effort per task is something I was already doing, by hand.

## Setup: CLAUDE.md, imports, rules

The talk cites an ETH Zurich study where bloated `CLAUDE.md` files cost about 3 percent in quality and 20 percent in tokens. I didn't reproduce that and won't repeat the numbers as mine. The advice that follows from it is sound anyway: keep the main file small and split the rest out.

`@path` imports work. I put a codeword in `team-rules.md`, referenced it from `CLAUDE.md` with `@team-rules.md`, and asked a headless Haiku session for it:

```bash
$ claude -p --model haiku "What is the codeword in your project instructions? Reply with only the codeword."
HERONFISH-42
```

My own setup already uses the rules directory. `~/.claude/rules/` holds six files: a comment ban, diff discipline, testing, tickets, voice, and one for what may appear on public surfaces like this blog. They load into every session. `/context` says they cost 5.8k tokens together.

## permissions.deny is not a secret barrier

The talk points to `permissions.deny` in `settings.json` for keeping secrets like production keys away from the model. I wanted to see where that stops.

A scratch project, a fake key, and one deny rule:

```bash
$ cat .env
API_KEY=sk-fake-0000-canary
$ cat .claude/settings.json
{"permissions":{"deny":["Read(./.env)"]}}
```

Then I ran headless Haiku sessions with Bash allowed, each told to run one exact command:

| Command | Deny in place | Result |
|---|---|---|
| Read tool on `.env` | yes | blocked |
| `cat .env` | yes | blocked |
| `cat .env` | no (control) | key printed |
| `cat .e?v` | yes | **key printed** |

The control matters. Without it, "blocked" could just mean headless mode refuses everything. With it, you can see the deny rule is doing the work. It also covers `cat` on the literal path. But it matches the path as written, and a glob that resolves to the same file went straight through.

So a deny rule is a guardrail, not a security boundary. Each time Haiku was blocked, it stopped and said it would not look for a way around the rule. That is the model choosing to comply, not the rule holding. This is documented. The [permissions page](https://code.claude.com/docs/en/permissions#what-a-bash-rule-doesnt-match) says a deny rule "covers the invocation Claude usually produces and isn't a security boundary", and points to the sandbox for real enforcement. The glob test shows how little it takes to step around one. If a secret must not reach the model, it shouldn't be readable from the working tree at all. Use a secret manager, a sandbox, or a container that never mounts it.

I use deny rules for something else. My list blocks `make`, `cmake`, `colcon`, `pip install`, `python3`, `sudo` and running `./` binaries on the host. That isn't about secrets. It forces every build and test into Docker.

## Daily workflow: what I tried

I tried four of the interactive ones in a real session:

| Feature | Verdict |
|---|---|
| Shift+Tab plan mode, then Ctrl+G to edit the plan in my editor | kept |
| Double-Esc / `/rewind` | kept |
| Ctrl+S to stash a half-typed prompt | meh |
| `/focus` | dropped |

The talk's case for Ctrl+G is that arguing with a plan in chat costs a round trip per correction, while editing the Markdown directly costs none. The case for rewind is that a wrong turn leaves bad assumptions in the context, not just bad code, and rewinding removes both. Both stuck.

The rest I haven't tried yet: `/statusline`, `/color`, `/voice`, `/doctor`, `claude agents` and Remote Control. `/doctor` prints nothing when run headless, so it needs an interactive session.

## Context: the "40 percent dump zone"

The talk says output quality degrades past roughly 40 percent of the context window. It suggests running `/context` in a fresh session to see how much your config eats before you type anything. `/context` works headless, so here is mine from a fresh session in this blog's repo:

| Category | Tokens |
|---|---|
| System prompt | 2.4k |
| System tools | 5.4k |
| MCP tools (loaded) | 0.7k |
| MCP server instructions | 1.8k |
| Memory files (CLAUDE.md + rules) | 5.8k |
| Skills | 5.6k |
| **Total** | **21.7k of 1M (2%)** |
| MCP tools (deferred, not loaded) | 30.8k |

I have several MCP servers connected, with dozens of tools each, and they cost almost nothing up front. Tool schemas are deferred: the model sees only the names and loads a full schema when it needs one. In a scratch directory the deferred pile was 59.1k tokens and the loaded total 21.9k.

The 2% is of a 1M window. On a 200k window the same 21.7k would be about 11%, still well under the talk's 40%. Either way, setup isn't what fills my context. I use `/clear` far more than `/compact` (184 against 14). My `/done` skill writes a handoff note first, so a fresh session picks up from that instead of from a summary.

## Headless: claude -p

`claude -p` runs one prompt, prints the answer and exits, so it pipes like any other Unix tool:

```bash
$ git log --since=2026-10-01 --format='%s' | claude -p --model haiku \
    "These are commit subjects from my blog repo this month. In two sentences, what did I work on?"
```

It came back with a two-sentence summary of my October: the arena allocator post, narration audio, fixed Godbolt embeds, and SEO fixes. That's the talk's "quarterly review" idea in one line. It's also how I ran every experiment in this post.

## What stuck

Ctrl+G and rewind stuck. Ctrl+S was meh. `/focus` got dropped. `/goal`, `/btw`, `/rename` and `!` had already stuck before I watched the talk.

The talk makes one more point in its last section: when a prompt keeps working, make it a skill. The top of my history is skills, not built-in commands.
