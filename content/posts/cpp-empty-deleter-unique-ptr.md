---
title: 'A unique_ptr With a Custom Deleter That Costs Zero Bytes'
date: 2026-10-20
draft: false
cover:
  image: /images/posts/cpp-empty-deleter-unique-ptr.png
  alt: 'unique_ptr with an empty lambda deleter stays 8 bytes; a function-pointer deleter doubles it to 16'
tags:
- C++
- compilers
- GCC
- optimization
keywords:
- unique_ptr custom deleter size
- unique_ptr fclose deleter
- empty deleter unique_ptr
- static lambda C++23
- lambda in unevaluated context C++20
- no_unique_address unique_ptr
- empty base optimization deleter
- sizeof unique_ptr function pointer deleter
- decltype lambda deleter alias template
categories:
- deep-dive
summary: 'Wrapping a C handle in unique_ptr with a function-pointer deleter doubles
  the pointer to 16 bytes. Putting the function into the deleter type instead, with
  an alias template over decltype of a static lambda, brings it back to 8. Sizes checked
  on GCC 14.2, GCC 16.2, Clang 22.1 and MSVC 19.44, with live Godbolt sessions.'
ShowToc: true
audio:
  pronunciation:
    std::unique_ptr: S T D unique pointer
    unique_ptr: unique pointer
    unique_ptr_deleter: unique pointer deleter
    fclose: F close
    tmpfile: temp file
    decltype: decl type
    sizeof: size of
    no_unique_address: no unique address
    libstdc++: lib S T D C plus plus
    MSVC: M S V C
    Godbolt: god bolt
    C++20: C plus plus twenty
    C++23: C plus plus twenty three
    EBO: E B O
---

Every C library hands you a pointer and a function to free it. `FILE*` and `fclose`. `SDL_Window*` and `SDL_DestroyWindow`. The first thing most people write is this:

```cpp
std::unique_ptr<FILE, int (*)(FILE*)> file{std::fopen(path, "r"), fclose};
```

It works. It is also twice the size of the pointer it wraps, because the function pointer is stored next to the `FILE*` in every object. The function never changes. There is no reason to carry it around at runtime.

## The trick

Put the function into the deleter's *type*:

```cpp
template <typename T, auto DeleteFn>
using unique_ptr_deleter =
    std::unique_ptr<T, decltype([](T* p) static noexcept { DeleteFn(p); })>;

using file_ptr = unique_ptr_deleter<FILE, fclose>;

auto file = file_ptr{std::tmpfile()};
```

`DeleteFn` is a non-type template parameter, so `fclose` is baked into the lambda's body at compile time. The lambda captures nothing, so its closure type is an empty class. `unique_ptr` stores an empty deleter for free.

## Sizes

I compiled the same file with four compilers. Each size is enforced by a `static_assert`, so a compile with exit code 0 means the size holds. GCC and Clang also ran the program and printed the numbers.

| type | GCC 14.2 | GCC 16.2 | Clang 22.1 | MSVC 19.44 x64 |
|---|---|---|---|---|
| `FILE*` | 8 | 8 | 8 | 8 |
| `unique_ptr<FILE, lambda>` | 8 | 8 | 8 | 8 |
| `unique_ptr<FILE, int(*)(FILE*)>` | 16 | 16 | 16 | 16 |
| `unique_ptr<FILE, stateful functor>` | 16 | 16 | 16 | 16 |

The stateful functor is a struct holding the function pointer as a member. It shows that the gain comes from the deleter being empty, not from it being a functor.

```
unique_ptr<FILE, int(*)(FILE*)>            16 bytes
+--------------------+--------------------+
| FILE*  ptr         | int(*)(FILE*) del  |
| 8 bytes            | 8 bytes            |
+--------------------+--------------------+

unique_ptr<FILE, decltype([](FILE*) static {...})>   8 bytes
+--------------------+
| FILE*  ptr         |   deleter: empty class, no storage
| 8 bytes            |
+--------------------+
```

{{< godbolt id="ddvcrcKzP" >}}

MSVC can't execute on Godbolt, so it is compile-only. The `static_assert`s still prove the layout: [godbolt.org/z/s4bb8G67f](https://godbolt.org/z/s4bb8G67f).

## Why the empty deleter is free

`unique_ptr` has to store a pointer and a deleter. A plain struct with an empty member still pays at least one byte for it, and then padding rounds that up to 8. The standard libraries avoid that.

libstdc++ (GCC 14) keeps a `tuple<pointer, _Dp>` inside `__uniq_ptr_impl`. Its tuple marks empty, non-final element types `[[no_unique_address]]` (see `_Head_base` in `<tuple>`), so the deleter takes no space. MSVC's STL uses its own compressed pair, which gets the same result through the empty base optimization. Different mechanism, same 8 bytes.

So the whole point is to make the deleter an empty type. A function pointer can never be one. A capture-less lambda always is.

## Which standard each piece needs

- **Lambda inside `decltype`** needs C++20. Lambdas in unevaluated operands were not allowed before. GCC 14 with `-std=c++17` says: `lambda-expression in unevaluated context only available with '-std=c++20'`.
- **`static` on the lambda** needs C++23. With `-std=c++20 -pedantic-errors`, GCC 14 rejects it: `'static' only valid in lambda with '-std=c++23'`.

The `static` doesn't change the size. A capture-less lambda is empty either way. What it does is make `operator()` a static member function, so the call has no implicit `this`. At `-O2` the call inlines anyway, so I would not expect a measurable difference. I keep it because it says what I mean: this deleter has no state.

If you are stuck on C++20, drop `static` and you still get 8 bytes: [godbolt.org/z/YqnEj13Y5](https://godbolt.org/z/YqnEj13Y5).

## One caveat about `fclose`

I include `<stdio.h>` and use `::fclose`, not `std::fclose`. The standard only lets you take the address of functions in namespace `std` that are explicitly marked addressable, and `std::fclose` is not one of them. Passing it as a template argument is technically unspecified. The global C function from `<stdio.h>` doesn't have that problem. GCC 14.2, Clang 22.1 and MSVC 19.44 all accepted `std::fclose` too, but I'd rather not depend on it.

## The full program

```cpp
#include <cstdio>
#include <memory>
#include <stdio.h>

template <typename T, auto DeleteFn>
using unique_ptr_deleter =
    std::unique_ptr<T, decltype([](T* p) static noexcept { DeleteFn(p); })>;

struct stateful_closer {
    int (*close)(FILE*);
    void operator()(FILE* f) const noexcept { close(f); }
};

using file_lambda  = unique_ptr_deleter<FILE, fclose>;
using file_fnptr   = std::unique_ptr<FILE, int (*)(FILE*)>;
using file_functor = std::unique_ptr<FILE, stateful_closer>;

static_assert(sizeof(file_lambda) == sizeof(FILE*));
static_assert(sizeof(file_fnptr) == 2 * sizeof(FILE*));
static_assert(sizeof(file_functor) == 2 * sizeof(FILE*));

int main() {
    std::printf("FILE*                         %zu\n", sizeof(FILE*));
    std::printf("unique_ptr<FILE, lambda>      %zu\n", sizeof(file_lambda));
    std::printf("unique_ptr<FILE, int(*)(...)> %zu\n", sizeof(file_fnptr));
    std::printf("unique_ptr<FILE, functor>     %zu\n", sizeof(file_functor));

    auto file = file_lambda{std::tmpfile()};
    if (!file) {
        std::puts("tmpfile failed");
        return 1;
    }
    std::fputs("closed by the empty deleter\n", file.get());
    std::puts("file open, closes at scope exit");
}
```

Output, identical on GCC 14.2, GCC 16.2 and Clang 22.1 (x86-64, `-std=c++23 -O2`):

```
FILE*                         8
unique_ptr<FILE, lambda>      8
unique_ptr<FILE, int(*)(...)> 16
unique_ptr<FILE, functor>     16
file open, closes at scope exit
```
