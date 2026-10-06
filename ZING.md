# zing basics

A short tour of the language. Everything here is tested and working today.

```bash
zing run program.zig     # run a file
zing repl               # interactive prompt
```

---

## 1. Hello, world

```zig
print("hello, world")
```

`print` accepts any value: strings, numbers, lists, maps, objects.

---

## 2. Variables

`let` declares a name. Types are inferred, and there are no separate int/float
types to fight — `3` and `3.0` both work, and mixing them is fine.

```zig
let name = "jai"
let count = 10
let ratio = 0.75
```

Names ending in `_` are conventionally private to a module.

---

## 3. Numbers

Integers and floats are the same number type. Division always produces a float.

```zig
print(7 / 2)        // 3.5
print(7 + 2 * 3)    // 13
print(10 % 3)       // 1
print(2.0 * 4)      // 8.0
```

---

## 4. Conditionals

`elif` is spelled with an `e`. Blocks use braces.

```zig
let n = 7
if n < 5 {
    print("small")
} elif n < 10 {
    print("medium")
} else {
    print("large")
}
```

---

## 5. Loops

Three forms. Ranges use `0..10`, which excludes the upper bound.

```zig
let x = 0
for i in 0..5 { print(i) }             // 0 1 2 3 4
while x < 3 { print(x); x = x + 1 }    // while with a condition
for item in [10, 20, 30] { print(item) }   // any list
```

`for` also walks maps (over their keys) and strings (over characters):

```zig
for key in {"a": 1, "b": 2} { print(key) }   // a  b
for ch in "abc" { print(ch) }                 // a  b  c
```

Use `break` to stop early and `continue` to skip one iteration.

---

## 6. Functions

```zig
func add(a, b) {
    return a + b
}
print(add(2, 3))
```

Parameters can have defaults:

```zig
func greet(name, greeting = "hello") {
    return greeting + ", " + name
}
print(greet("jai"))            // hello, jai
print(greet("jai", "hi"))      // hi, jai
```

---

## 7. Lists (arrays)

```zig
let xs = [1, 2, 3]
push(xs, 4)              // append
print(len(xs))           // 4
print(xs[0])             // 1
print(pop(xs))           // 4, and removes it
```

Slices work like Python's:

```zig
let xs = [0, 1, 2, 3]
print(xs[1:3])     // [1, 2]
print(xs[:2])      // [0, 1]
print(xs[2:])      // [2, 3]
print(xs[-2:])     // [2, 3]
```

---

## 8. Maps (dictionaries)

```zig
let ages = {"jai": 20, "sam": 22}
print(ages["jai"])            // 20
print(has(ages, "sam"))       // true
for key in ages { print(key) }
```

---

## 9. Strings

Double quotes. `+` joins strings.

```zig
let s = "zing"
print(upper(s))              // ZING
print(s[1:4])                // aip
print(join(split("a,b,c", ","), " | "))   // a | b | c
print(replace(s, "j", "J"))  // Zing
print(starts_with(s, "jai")) // true
print(repeat("ab", 3))       // ababab
```

Useful ones: `upper lower strip lstrip rstrip split join replace find
starts_with ends_with contains repeat count ord chr`.

---

## 10. Errors and recovery

`try` runs a block. If something fails, a `catch` handles it; `finally` always
runs. `else` runs only when nothing went wrong.

```zig
try {
    let data = read(open("config.txt", "r"))
    print(data)
} catch as e {
    print("could not read it: " + e)
} finally {
    print("done either way")
}
```

Raising your own error is `throw`:

```zig
func check(age) {
    if age < 0 {
        throw "age cannot be negative"
    }
    return "ok: " + str(age)
}
```

A `catch` clause can filter by error name:

```zig
try {
    let f = open("missing.txt", "r")
} catch RuntimeError {
    print("could not open it")
}
```

Any failure — including division by zero and bad indexes — arrives as a
`RuntimeError` with a message written for the person reading it, so it can be
caught like any other.

---

## 11. Files

```zig
let f = open("notes.txt", "w")
write_line(f, "first line")
close(f)

let g = open("notes.txt", "r")
for line in read_lines(g) {
    print(strip(line))
}
close(g)

print(file_exists("notes.txt"))
print(list_dir("."))
remove_file("notes.txt")
```

Modes: `r` read, `w` write (truncates), `a` append, `x` create only.

---

## 12. Classes and objects

```zig
class Dog {
    func new(name) {
        self.name = name
    }

    func speak() {
        return self.name + " says woof"
    }
}

let d = new Dog("Rex")
print(d.speak())
```

A class with no `new` method is an abstract base: it supplies behaviour for
subclasses but cannot be instantiated on its own.

Inheritance uses `extends`, and methods can be overridden:

```zig
class Animal {
    func new(name) { self.name = name }
    func speak() { return "..." }
}

class Cat extends Animal {
    func speak() { return self.name + " meow" }
}

print(new Cat("Tom").speak())   // Tom meow
```

Fields are declared by assigning to `self` inside `new`.

---

## 13. Splitting a program across files

Put helpers in a `.zig` file next to your main program:

```zig
// mathlib.zig
func square(n) { return n * n }
let VERSION = 1
```

```zig
// requires: file mathlib.zig beside this one
// main.zig -- needs mathlib.zig beside it
import mathlib
print(square(7))    // 49
print(VERSION)      // 1
```

Anything in the file is available after the import. Names starting with `_`
stay private to the module. Importing the same file twice loads it only once.

---

## 14. Constants

`PI`, `E` and `TAU` are built in:

```zig
print(round(PI, 4))    // 3.1416
print(round(PI * 2, 4))  // 6.2832
```

---

## 15. Standard library reference

**Math** `sin cos tan asin acos atan atan2 log log2 log10 exp floor ceil round abs min max sum pow sign sqrt`

**Strings** `upper lower strip lstrip rstrip split join replace find starts_with ends_with contains repeat count ord chr is_empty`

**Lists** `len push pop range(start, stop, step)`

**Maps** `len keys values has`

**Files** `open read read_line read_lines write write_line close file_exists list_dir remove_file`

**Other** `print str int float type input exit clock`

`min`, `max` and `sum` take either a list or loose arguments:

```zig
print(max([3, 9, 2]))    // 9
print(max(3, 9, 2))      // 9
```

---

## 16. Calling C++ (optional)

```zig
// requires: module gpp (the optional C++ bridge)
import gpp
print(gpp.abs(-5))
```

This shells out to a C++ compiler the first time. It is entirely optional — the
language itself needs nothing but Python 3.11 or newer, and no network access.

---

## What comes next

Not yet available: list and map comprehensions, `for i, value in` pairs,
generators, nested functions and closures, context managers, sets, and
decorators. Each is a planned addition; check the tests in `tests/` for the
exact current state of the language.