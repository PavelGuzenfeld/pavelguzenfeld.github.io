---
title: Why DDS Content Filter Parameters Silently Fail for Strings in ROS 2
date: 2026-04-04
draft: false
tags:
- ROS2
- DDS
- Fast-DDS
- content-filter
- debugging
- open-source
- rmw
keywords:
- DDS content filter parameters
- Fast DDS DDSSQLFilter
- ROS 2 content filter string
- rmw_fastrtps content filter fix
cover:
  image: /images/posts/dds-content-filter.png
  alt: DDS Content Filter String Parameters in ROS 2
categories:
- deep-dive
summary: DDS content filter parameter substitution (%0, %1) silently fails for string
  fields in ROS 2 with Fast DDS. The root cause is three layers deep — the DDS SQL
  grammar requires quoted string literals, but no ROS 2 layer adds the quotes. Here's
  how I traced it and where to fix it.
ShowToc: true
audio:
  pronunciation:
    ROS 2: ross two
    ROS2: ross two
    ros2: ross two
    DDS: D D S
    Fast DDS: fast D D S
    Fast-DDS: fast D D S
    Cyclone DDS: cyclone D D S
    rclpy: R C L pie
    rcl: R C L
    rmw: R M W
    rmw_fastrtps: R M W fast R T P S
    DDSFilterParameter: D D S filter parameter
    DDSSQLFilter: D D S sequel filter
    DDSFilterGrammar: D D S filter grammar
    ros2cli: ross two C L I
    ros2 topic echo: ross two topic echo
    eProsima: ee Pro see ma
    OMG: O M G standards body
    create_content_filtered_topic: create content filtered topic
    ContentFilterOptions: content filter options
    PEG: P E G
    '%0': percent zero
    '%1': percent one
    GitHub: git hub
    GStreamer: G streamer
    PR: P R
---

## The Problem

I was adding `--content-filter` support to `ros2 topic echo|hz|bw` ([ros2/ros2cli#1213](https://github.com/ros2/ros2cli/pull/1213)) when I hit this:

```bash
ros2 topic echo --content-filter "data = %0" /topic std_msgs/String \
  --content-filter-params hello
```

Expected: messages where `data` equals `hello` are printed.

Actual:

```
PARSE ERROR: :1:0(0): parse error matching
  eprosima::fastdds::dds::DDSSQLFilter::Literal
```

The subscription silently falls back to unfiltered mode. No crash, no warning at the ROS 2 level — just a DDS error buried in stderr. The filter parameter is ignored and every message comes through.

The same expression with an inline literal works fine:

```bash
ros2 topic echo --content-filter "data = 'hello'" /topic std_msgs/String
```

So the issue is specifically with `%0` parameter substitution for string-typed fields.

---

## Tracing the Problem

### Layer 1: The DDS SQL Grammar

DDS content filter expressions use a subset of SQL. The grammar, defined in the [DDS specification (Annex B)](https://www.omg.org/spec/DDS/1.4/PDF), includes:

```
ComparisonPredicate ::= FieldName RelOp Parameter
                      | FieldName RelOp LiteralValue
Parameter           ::= %n      (where n < 100)
STRING              ::= any characters encapsulated in single quotes
```

A `Parameter` is a placeholder — `%0`, `%1`, etc. — whose value is supplied at runtime through the `expression_parameters` vector. The spec says parameter values should be typed, but it doesn't spell out how. That's left to the implementation.

### Layer 2: Fast DDS's Parameter Parser

Fast DDS implements parameter value parsing in [`DDSFilterParameter::set_value()`](https://github.com/eProsima/Fast-DDS/blob/master/src/cpp/fastdds/topic/DDSSQLFilter/DDSFilterParameter.cpp):

```cpp
bool DDSFilterParameter::set_value(const char* parameter)
{
    auto node = parser::parse_literal_value(parameter);
    if (!node) {
        return false;  // <-- our failure
    }
    copy_from(*node->left().value, false);
    value_has_changed();
    return true;
}
```

`parse_literal_value()` uses the PEG grammar in `DDSFilterGrammar.hpp`:

```cpp
struct Literal : sor< boolean_value, float_value, hex_value,
                      integer_value, char_value, string_value > {};
struct string_value : seq< open_quote, string_content, close_quote > {};
struct open_quote : one< '`', '\'' > {};
```

When you pass the parameter value `hello`, the parser tries to match it against each alternative:

| Rule | Input `hello` | Result |
|------|--------------|--------|
| `boolean_value` | Not `TRUE`/`FALSE` | fail |
| `float_value` | Doesn't start with digit/dot | fail |
| `hex_value` | Not `0x...` | fail |
| `integer_value` | Not a digit | fail |
| `char_value` | Not a quoted char | fail |
| `string_value` | Doesn't start with `'` or `` ` `` | **fail** |

Every alternative fails. The parser returns `nullptr`. `set_value()` returns `false`. Fast DDS logs the parse error and the subscription falls back to unfiltered mode.

The fix from Fast DDS's perspective is documented in [eProsima/Fast-DDS#4199](https://github.com/eProsima/Fast-DDS/issues/4199): you must include the quotes *in the parameter value itself*:

```cpp
// Wrong: parameters.push_back("hello");
// Right:
parameters.push_back("'hello'");
```

eProsima closed the issue as "not a bug." From the DDS spec's perspective, they have a point — `STRING` is defined as characters encapsulated in single quotes. The parameter value is parsed as a literal, and string literals need quotes.

### Layer 3: The ROS 2 Middleware Stack

Here's the path a parameter takes from your CLI to Fast DDS:

```
ros2 topic echo --content-filter-params hello
        |
        v
rclpy ContentFilterOptions(expression_parameters=['hello'])
        |
        v
rcl rmw_subscription_content_filter_options_set()
        |
        v
rmw_fastrtps_shared_cpp::create_content_filtered_topic()
    for (i ...) {
      expression_parameters.push_back(options->data[i]);  // bare "hello"
    }
        |
        v
Fast DDS: participant->create_contentfilteredtopic(
    ..., expression_parameters)  // DDSFilterParameter::set_value("hello") -> FAIL
```

**No layer adds quotes.** The string `hello` passes through rclpy, rcl, rmw, and arrives at Fast DDS completely unmodified. Fast DDS tries to parse it as a DDS literal, fails, and silently falls back.

---

## Where to Fix It

Three options, each at a different layer:

### Option A: Fast DDS (`DDSFilterParameter::set_value`)

Add a fallback: if `parse_literal_value()` fails, retry with the value wrapped in single quotes.

```cpp
bool DDSFilterParameter::set_value(const char* parameter)
{
    auto node = parser::parse_literal_value(parameter);
    if (!node) {
        std::string quoted = std::string("'") + parameter + "'";
        node = parser::parse_literal_value(quoted.c_str());
        if (!node) return false;
    }
    // ...
}
```

**Pro:** Fixes it for all DDS users, not just ROS 2.
**Con:** eProsima considers current behavior correct. PR likely rejected.

### Option B: rmw_fastrtps (the adapter layer)

Auto-quote bare strings before passing them to Fast DDS. This is the adapter between ROS 2 and a specific DDS vendor — exactly the right place for vendor-specific quirks.

```cpp
// rmw_fastrtps_shared_cpp/utils.hpp
inline std::string ensure_dds_literal(const std::string& value) {
    if (value.empty()) return "'" + value + "'";

    // Already quoted
    if ((value.front() == '\'' || value.front() == '`') &&
        value.size() >= 2 && value.back() == value.front())
        return value;

    // Boolean
    if (value == "TRUE" || value == "FALSE") return value;

    // Numeric (int, float, hex)
    const char* p = value.c_str();
    if (*p == '+' || *p == '-') ++p;
    if (*p == '0' && (*(p+1) == 'x' || *(p+1) == 'X')) return value;
    if (std::isdigit(*p) || *p == '.') return value;

    // Bare string — wrap in quotes
    return "'" + value + "'";
}
```

**Pro:** Fast DDS-specific, other rmw implementations unaffected. Backward compatible — already-valid literals pass through unchanged.
**Con:** It's a heuristic. Edge cases exist (e.g., a string that looks like a number but should be quoted).

### Option C: ros2cli (the CLI layer)

Have the CLI wrap string parameters before passing them to rclpy.

**Pro:** Simplest change.
**Con:** Every tool and library using content filters would need the same fix. Leaky.

### The Choice

Option B. The rmw layer is the adapter between the ROS 2 abstraction and the DDS implementation. Vendor quirks belong here. The heuristic is conservative — it only auto-quotes values that don't look like any valid DDS literal type.

---

## The Fix

PR: [ros2/rmw_fastrtps#873](https://github.com/ros2/rmw_fastrtps/pull/873)

Two call sites needed updating, both in `rmw_fastrtps_shared_cpp`:

1. **`create_content_filtered_topic()`** in `utils.cpp` — subscription creation
2. **`__rmw_subscription_set_content_filter()`** in `rmw_subscription.cpp` — dynamic filter updates

The `ensure_dds_literal()` function is added to `utils.hpp` as an inline utility, with `prepare_content_filter_parameters()` wrapping the loop. Both call sites now use the same path.

Unit tests cover: bare strings, already-quoted strings, backtick-quoted strings, booleans, integers, floats, hex, and empty strings. Eight test cases, all passing.

### Before and After

```bash
# Before: silently falls back to unfiltered (all messages delivered)
ros2 topic echo --content-filter "data = %0" /topic std_msgs/String \
  --content-filter-params hello

# After: only messages where data='hello' are delivered
ros2 topic echo --content-filter "data = %0" /topic std_msgs/String \
  --content-filter-params hello
```

---

## The Bigger Picture: Content Filter CLI Support

The rmw fix was discovered while adding `--content-filter` to the ros2 CLI tools ([ros2/ros2cli#1213](https://github.com/ros2/ros2cli/pull/1213)). This PR adds two new arguments to `ros2 topic echo`, `hz`, and `bw`:

```bash
# Filter at the DDS middleware level — only matching messages
# are delivered to the subscriber
ros2 topic echo --content-filter "data LIKE '%sensor%'" /diagnostics

# With parameterized expressions
ros2 topic echo --content-filter "temperature > %0" /weather \
  --content-filter-params 30.0
```

The key difference from the existing `--filter` flag: content filters are applied by the DDS middleware *before* messages reach the subscriber. This means:

- **Reduced bandwidth** — filtered messages never cross the network
- **Reduced CPU** — no deserialization of rejected messages
- **No security risk** — unlike `--filter` which evaluates arbitrary Python expressions

The test suite covers happy paths (matching/non-matching filters), edge cases (`--once` with content filter, combined DDS + Python filtering), and contract tests for argument parsing across all three verbs.

---

## Lessons Learned

**Silent failures are the worst kind.** The DDS parse error was logged to stderr by Fast DDS, but rclpy didn't propagate it. The subscription was created successfully — it just didn't filter. In production, you'd see all messages coming through and have no idea the filter was ignored.

**The adapter layer is where vendor quirks belong.** The DDS spec leaves parameter value formatting to implementations. Fast DDS chose strict literal parsing. Cyclone DDS might handle it differently. The rmw layer exists precisely to absorb these differences.

**Test in Docker against the actual middleware.** I caught the `%0` failure only because I ran integration tests in `osrf/ros:rolling-desktop`. Unit tests with mocked subscriptions would have passed.

**Read closed issues.** eProsima/Fast-DDS#4199 was closed in 2023 as "not a bug." The workaround was documented in the comments. Three years later, the same issue still trips up ROS 2 users because no layer in the stack applies the workaround automatically.

---

## Links

- **CLI PR:** [ros2/ros2cli#1213](https://github.com/ros2/ros2cli/pull/1213) — `--content-filter` for echo/hz/bw
- **rmw fix:** [ros2/rmw_fastrtps#873](https://github.com/ros2/rmw_fastrtps/pull/873) — auto-quote bare string params
- **Fast DDS issue:** [eProsima/Fast-DDS#4199](https://github.com/eProsima/Fast-DDS/issues/4199) — original report
- **DDS grammar file:** [`DDSFilterGrammar.hpp`](https://github.com/eProsima/Fast-DDS/blob/master/src/cpp/fastdds/topic/DDSSQLFilter/DDSFilterGrammar.hpp)
- **DDS spec:** [OMG DDS 1.4, Annex B](https://www.omg.org/spec/DDS/1.4/PDF) — content filter expression syntax
