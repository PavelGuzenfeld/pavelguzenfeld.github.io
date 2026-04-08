# Social Media Campaign — pavelguzenfeld.com

Goal: Convert technical followers into consulting clients.

---

## Strategy

**Funnel:** X/LinkedIn posts (awareness) → Blog posts (credibility) → Consulting page (conversion)

**Core principle:** Show the work, not the pitch. Let expertise sell itself. Never say "hire me" directly — post about bugs found, fixes shipped, performance wins. People read these and think "I want this person looking at my codebase."

---

## Platforms

### Tier 1 — Consistent presence

| Platform | Why | Who's there | Frequency |
|----------|-----|-------------|-----------|
| **X/Twitter** (@PavelGuzenfeld) | Where C++/robotics devs hang out. Fast, public, shareable | Engineers, maintainers, CTOs | 3x/week |
| **LinkedIn** | Where hiring decisions happen. Longer shelf life per post | Engineering managers, CTOs, recruiters | 2x/week |

### Tier 2 — Selective posting

| Platform | Why | Who's there | Frequency |
|----------|-----|-------------|-----------|
| **Reddit** (r/cpp, r/ROS, r/drones) | Deep technical audiences, posts live forever in search | Engineers researching solutions | Best articles only |
| **Hacker News** (news.ycombinator.com) | One front-page hit = thousands of qualified visitors | Senior engineers, founders | Best articles only |
| **ROS Discourse** | Official ROS community — direct credibility from merged PRs | ROS users who might need help | When relevant |
| **PX4 Discuss** | Official PX4 forum — 7 upstream PRs give credibility | Drone teams using PX4 | When relevant |

### Skip for now

YouTube, Dev.to, Medium, Discord, Instagram, TikTok — wrong audience or low ROI for consulting.

---

## Content Types

### 1. Technical insight (Mon)
Short post showing deep knowledge. No link needed.
- "Here's why GStreamer shmsink always exits with code 1..."
- "TIL Eigen's TensorUInt128 division loops forever if the dividend exceeds 2^127..."

### 2. PR/contribution highlight (Wed)
"I just got this merged" with what it fixes and why it matters.
- "Just got merged into Eigen: fix for vectorized erf returning NaN at ±inf"
- "Fixed O(N²) entity addition in ROS 2's CallbackGroup — 71x speedup. PR #3109"

### 3. Blog post share (Fri)
Link to a deep-dive article with a compelling hook — not "check out my blog" but a specific problem/insight.
- "I found 4 bugs in GStreamer's shared memory elements. A race condition, a use-after-free, a wrong-pointer dereference, and a page alignment mismatch. Here's what they have in common →"

### 4. Engagement (ongoing)
Reply to C++/ROS/PX4/drone discussions with genuine insight. Not self-promotion — actually help people.

---

## Soft CTA Pattern

Every ~5th post, end with a soft call to action:
- "If your drone team is fighting GStreamer shared memory bugs, I've seen all of them. DM or me@pavelguzenfeld.com"
- "I help UAV teams debug and stabilize flight-critical C++ systems. pavelguzenfeld.com/consulting"

**Bio (X):** "UAV & Robotics Software Engineer — C++23. I help drone teams build reliable flight software. pavelguzenfeld.com/consulting"

**Pinned tweet:** Strongest "I found and fixed this" story with consulting page link.

---

## Content Calendar — Week 1

| Day | Platform | Type | Content |
|-----|----------|------|---------|
| Mon | X | Technical insight | Thread about a specific bug fix (e.g., GStreamer shmsink exit code) |
| Mon | LinkedIn | Same content | Adapted for professional tone |
| Wed | X | PR highlight | "Just shipped" post about a notable merged PR |
| Fri | X + LinkedIn | Blog share | Share one deep-dive article with a hook |
| Fri | Reddit r/cpp | Blog share | Post the Eigen or C++ library article |

---

## Blog Posts Ranked by Social Potential

### Best for X/LinkedIn (broad C++ audience)
1. Fixing O(N²) Entity Addition in ROS 2's CallbackGroup — performance win, relatable
2. Anatomy of Four GStreamer Shared Memory Bugs — compelling narrative
3. Fixing an Infinite Loop in Eigen's 128-bit Integer Division — satisfying one-liner fix
4. Modified Gram-Schmidt vs Householder QR — benchmark data, visual

### Best for Reddit r/cpp
1. behavior-tree-lite project page — comparison table vs BehaviorTree.CPP
2. strong-types project page — comparison table vs mp-units/Au/nholthaus
3. Gram-Schmidt vs Householder QR benchmark
4. GCC false-positive warnings in Eigen

### Best for Hacker News
1. Anatomy of Four GStreamer Shared Memory Bugs — deep debugging narrative
2. Contributing to ROS 2 — A Practical Guide — "here's how open source actually works"
3. Zero-Copy Video on Jetson: Building gst-nvmm-cpp — niche but impressive
4. PX4 SITL to Unity in Docker: A 60-Hour Debugging Odyssey — compelling title

### Best for ROS Discourse
1. Contributing to ROS 2 — A Practical Guide
2. Fixing O(N²) CallbackGroup
3. px4-ros2-interface-lib SITL testing

### Best for PX4 Discuss
1. PX4 Autopilot: Troubleshooting, Debugging, Building, and Testing
2. Migrating ROS Tests from Gazebo Classic to SIH
3. px4-ros2-interface-lib SITL testing

---

## Open Source as Trust Layer

Open-source visibility isn't a separate goal — it's the trust layer that makes consulting conversion work:

1. Someone sees an X post about fixing a GStreamer bug
2. They click the profile → see "pavelguzenfeld.com/consulting"
3. They check GitHub → 97 PRs across projects they recognize
4. They think "this person finds bugs in the tools I depend on"
5. They email

The portfolio is already built. The campaign makes sure the right people see it.

---

## Realistic Growth Expectations

| Timeframe | X Followers | What drives it |
|-----------|-------------|----------------|
| Month 1 | 50-200 | Initial posts, engaging in C++/ROS/PX4 threads |
| Month 3 | 200-500 | Consistent posting, blog posts getting shared |
| Month 6 | 500-1500 | If a post goes viral in C++ or drone community |
| Year 1 | 1000-3000 | Steady presence, recognized name in niche |

Follower count doesn't matter — the right 200 people seeing your work is worth more than 10K random followers. One CTO in the drone space is worth more than all of them.

---

## Tools

- **X posting:** twitter-mcp (installed, working via Claude Code)
- **Reddit:** Manual for now, or add reddit MCP later
- **LinkedIn:** Manual (API is restrictive)
- **HN:** Manual (submit at news.ycombinator.com/submit)
