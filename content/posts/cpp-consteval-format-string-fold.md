---
title: 'Building a "{}{}{}" Format String at Compile Time, Three Ways'
date: 2026-10-20
draft: true
tags:
- C++
- compilers
- GCC
keywords:
- consteval format string C++
- fmt::format compile time format string
- std::format format_string consteval
- index_sequence fold expression
- comma fold expression C++17
- templated lambda index_sequence C++20
- views::iota transform consteval
- concat variadic fmt
- static constexpr format string
categories:
- deep-dive
summary: 'A variadic concat(args...) that builds its own "{}{}{}" pattern at compile
  time, written three ways: a plain loop, a ranges pipeline, and an index_sequence
  with a comma fold. fmt 12 and std::format both still check the generated pattern
  at compile time, but only if it is static constexpr. Verified on GCC 14.2, GCC 16.2,
  Clang 22.1 and MSVC 19.44.'
ShowToc: true
audio:
  pronunciation:
    consteval: const eval
    constexpr: const expr
    fmt::format: F M T format
    std::format: S T D format
    std::println: S T D print line
    std::array: S T D array
    index_sequence: index sequence
    make_index_sequence: make index sequence
    views::iota: views iota
    views::transform: views transform
    ranges::copy: ranges copy
    sizeof...: size of dot dot dot
    libc++: lib C plus plus
    MSVC: M S V C
    Godbolt: god bolt
    C++20: C plus plus twenty
    C++23: C plus plus twenty three
---

I wanted a `concat` that glues any number of values into a string:

```cpp
auto s = concat(42, " rocket ", 3.14, " boot");  // "42 rocket 3.14 boot"
```

The lazy version builds `"{}{}{}{}"` at runtime and calls `fmt::format` with `fmt::runtime`. That throws away the one thing I like about fmt and `std::format`: a format string that doesn't match the arguments is a compile error. So the pattern has to exist at compile time. Its length depends only on `sizeof...(Args)`, so a `consteval` function can build it.

## Three ways to build the braces

All three return `std::array<char, 2 * N + 1>`. The array is value-initialized, so the last byte is already the `'\0'`.

**A loop.** Boring, and the easiest one to read.

```cpp
template <std::size_t N>
consteval auto braces() {
    std::array<char, 2 * N + 1> out{};
    for (std::size_t i = 0; i < N; ++i) {
        out[2 * i] = '{';
        out[2 * i + 1] = '}';
    }
    return out;
}
```

**A ranges pipeline.** `iota` produces indices 0 to 2N-1. Even indices become `'{'` and odd ones `'}'`.

```cpp
template <std::size_t N>
consteval auto braces() {
    std::array<char, 2 * N + 1> out{};
    std::ranges::copy(std::views::iota(std::size_t{0}, 2 * N)
                          | std::views::transform([](std::size_t i) { return i % 2 == 0 ? '{' : '}'; }),
                      out.begin());
    return out;
}
```

**An index_sequence with a comma fold.** No loop at all. The pack expands into N assignments.

```cpp
template <std::size_t N>
consteval auto braces() {
    std::array<char, 2 * N + 1> out{};
    [&]<std::size_t... I>(std::index_sequence<I...>) {
        ((out[2 * I] = '{', out[2 * I + 1] = '}'), ...);
    }(std::make_index_sequence<N>{});
    return out;
}
```

The fold is the only one that needs a second look. Here is what it does for N = 3:

```
std::make_index_sequence<3>{}   ->   std::index_sequence<0, 1, 2>
                                     so the lambda sees I... = 0, 1, 2

((out[2*I] = '{', out[2*I+1] = '}'), ...)

expands to

(out[0] = '{', out[1] = '}'),
(out[2] = '{', out[3] = '}'),
(out[4] = '{', out[5] = '}')

out:  '{'  '}'  '{'  '}'  '{'  '}'  '\0'
       0    1    2    3    4    5    6
```

The templated lambda (`[&]<std::size_t... I>`) is C++20. It lets me get at the pack without writing a separate helper function template. The comma fold itself has been around since C++17.

All three give the same bytes. The file checks it with `static_assert`, so it won't compile if they disagree:

```cpp
static_assert(with_loop::braces<3>() == with_ranges::braces<3>());
static_assert(with_loop::braces<3>() == with_fold::braces<3>());
```

## Feeding it to fmt

```cpp
template <typename... Args>
auto concat(const Args&... args) {
    static constexpr auto pattern = with_fold::braces<sizeof...(Args)>();
    return fmt::format(pattern.data(), args...);
}
```

I expected `pattern.data()` to be a problem. `fmt::format` takes a `fmt::format_string<Args...>`, whose constructor is `consteval`, and a `const char*` from `.data()` doesn't look like a compile-time string.

It works anyway. `pattern` is a `static constexpr` object, so the pointer to its first element is a constant expression, and fmt's `consteval` constructor can read the characters and check them against `Args...`. With fmt 12.0.0 this compiles and prints `42 rocket 3.14 boot` on GCC 14.2, GCC 16.2 and Clang 22.1. MSVC 19.44 compiles it as well.

{{< godbolt id="j3P7fTjTh" >}}

To make sure the check is real and not skipped, I broke it on purpose: build `sizeof...(Args) + 1` placeholders for four arguments. GCC 14 refuses it:

```
error: call to consteval function 'fmt::v12::fstring<const int&, const char (&)[9],
  const double&, const char (&)[6]>(pattern.std::array<char, 11>::data())'
  is not a constant expression
...
    if (arg_id >= ctx->num_args()) report_error("argument not found");
```

So the generated pattern is still checked against the real argument list. That is the behaviour I wanted.

## The `static` matters

Drop `static` and keep `constexpr`:

```cpp
constexpr auto pattern = with_fold::braces<sizeof...(Args)>();
```

Now `pattern` is a local variable with automatic storage. Its address isn't a constant expression, so the `consteval` constructor can't use it. GCC 14 with fmt 12:

```
error: call to consteval function 'fmt::v12::fstring<...>(pattern.std::array<char, 9>::data())'
  is not a constant expression
error: '...' is not a constant expression because it refers to an incompletely
  initialized variable
```

`std::format` fails the same way. Godbolt with GCC 16.2: [godbolt.org/z/9j98TEzd4](https://godbolt.org/z/9j98TEzd4).

The fix is not `fmt::runtime`. That would compile, but it turns the check off. The fix is the `static`.

## std::format works the same

Swap `fmt::format` for `std::format` and `fmt::print` for `std::println`, and nothing else changes:

```cpp
template <typename... Args>
auto concat(const Args&... args) {
    static constexpr auto pattern = with_fold::braces<sizeof...(Args)>();
    return std::format(pattern.data(), args...);
}
```

I ran it with GCC 14.2 (libstdc++), Clang 22.1 with libstdc++, and Clang 22.1 with `-stdlib=libc++`. All printed `42 rocket 3.14 boot`. MSVC 19.44 with `/std:c++latest` compiles it. The off-by-one pattern fails at compile time with libstdc++ too: `call to consteval function 'std::basic_format_string<...>(pattern.std::array<char, 11>::data())' is not a constant expression`.

{{< godbolt id="8hxezMWK8" >}}

## Which one I'd keep

The loop. The fold is fun, and it's the one that taught me how `index_sequence` packs expand, but the loop says the same thing in four lines a newcomer can read. The ranges version is the hardest to read and gains nothing here. All three run inside `consteval`, so none of them leaves any code behind at runtime.

## The full program

```cpp
#include <algorithm>
#include <array>
#include <cstddef>
#include <fmt/core.h>
#include <ranges>
#include <utility>

namespace with_loop {
template <std::size_t N>
consteval auto braces() {
    std::array<char, 2 * N + 1> out{};
    for (std::size_t i = 0; i < N; ++i) {
        out[2 * i] = '{';
        out[2 * i + 1] = '}';
    }
    return out;
}
}

namespace with_ranges {
template <std::size_t N>
consteval auto braces() {
    std::array<char, 2 * N + 1> out{};
    std::ranges::copy(std::views::iota(std::size_t{0}, 2 * N)
                          | std::views::transform([](std::size_t i) { return i % 2 == 0 ? '{' : '}'; }),
                      out.begin());
    return out;
}
}

namespace with_fold {
template <std::size_t N>
consteval auto braces() {
    std::array<char, 2 * N + 1> out{};
    [&]<std::size_t... I>(std::index_sequence<I...>) {
        ((out[2 * I] = '{', out[2 * I + 1] = '}'), ...);
    }(std::make_index_sequence<N>{});
    return out;
}
}

static_assert(with_loop::braces<3>() == with_ranges::braces<3>());
static_assert(with_loop::braces<3>() == with_fold::braces<3>());

template <typename... Args>
auto concat(const Args&... args) {
    static constexpr auto pattern = with_fold::braces<sizeof...(Args)>();
    return fmt::format(pattern.data(), args...);
}

int main() {
    fmt::print("{}\n", with_fold::braces<3>().data());
    fmt::print("{}\n", concat(42, " rocket ", 3.14, " boot"));
}
```

Output (GCC 14.2, GCC 16.2 and Clang 22.1, x86-64, `-std=c++23 -O2`, fmt 12.0.0):

```
{}{}{}
42 rocket 3.14 boot
```
