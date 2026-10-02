# jaipl

A small language for building things. Plain text files, no build step, no
toolchain to configure before your first program runs.

```jaipl
class Dog {
    let name
    func new(name) { self.name = name }
    func speak() { return self.name + " says woof" }
}

let d = new Dog("Rex")
print(d.speak())
```

Run it from any editor:

```
jaipl run dog.jai
```

## Install

**macOS and Linux** — one command, no `sudo`:

```sh
curl -fsSL https://jaivardhanpandey66-create.github.io/jaipl/install.sh | sh
```

That puts `jaipl` in `~/.local/bin`. Add `.jai` files to your desktop and to
the right-click menu with `--with-associate`.

**Windows** — download the installer from
[https://jaivardhanpandey66-create.github.io/jaipl](https://jaivardhanpandey66-create.github.io/jaipl). It bundles Python, so nothing needs
to be preinstalled, and it registers `.jai` so double-clicking runs the file.

**Any editor** — `.jai` is plain text and `jaipl` is a normal command, so
anything that can run a terminal command can run jaipl. There is a VS Code
extension on the Marketplace.

jaipl needs Python 3.11 or newer, and `g++` if you want the C++ bridge.

## Why it is shaped this way

The language is deliberately small, because the point is to get to a running
program before you have read a manual:

- `let` makes a value, `var` makes one you can change.
- Indentation is free. Braces or newlines end a statement; you rarely need
  either.
- Classes have fields, methods and one optional constructor named `new`.
  Inheritance is `extends`, and overridden methods dispatch the way you would
  hope.
- Errors point at the line and column and print a caret under the problem.
- An accidental infinite loop stops with a message instead of hanging.

## Language reference

### Values

`int`, `float`, `str`, `bool`, `null`, `list`, `map`, and your own classes.

```jaipl
let n = 42
let pi = 3.14
let name = "jaipl"
let ok = true
let nothing = null
let xs = [1, 2, 3]
let ages = {"rai": 19, "sam": 21}
```

### Variables

```jaipl
let name = "fixed"     // value
var count = 0          // you can reassign
count = count + 1
```

### Functions

```jaipl
func add(a, b = 10) {
    return a + b
}

print(add(1))        // 11
print(add(1, 2))     // 3
```

### Classes

```jaipl
class Animal {
    let name = "?"
    func speak() { return "..." }
    func describe() { return self.name + " says " + self.speak() }
}

class Dog extends Animal {
    let name = "Rex"
    func speak() { return "woof" }      // overrides Animal.speak
}

print(new Dog().describe())            // Rex says woof
```

A class's `new` method is its constructor, and it runs after the fields are
set up — including fields inherited from a base class.

```jaipl
class Point {
    let x
    let y
    func new(x, y) { self.x = x; self.y = y }
    func show() { return "(" + str(self.x) + ", " + str(self.y) + ")" }
}

print(new Point(3, 4).show())          // (3, 4)
```

### Control flow

```jaipl
let score = 7
if score > 10 { print("great") } elif score > 5 { print("ok") } else { print("low") }

let steps = 0
while steps < 3 {
    print("step " + str(steps))
    steps = steps + 1
}

for i in 0..5 { print(i) }             // 0 1 2 3 4
for pet in ["Rex", "Sam"] { print(pet) }
```

### Built-ins

`print` `len` `str` `int` `float` `input` `push` `pop` `range` `type` `has`
`keys` `values` `sqrt` `exit` `clock`

Lists and maps carry methods: `.push` `.pop` `.len` `.contains` `.join`
`.reverse` `.sort`, and maps carry `.keys` `.values` `.has`.

### Calling C++ from jaipl

```jaipl
import gpp

let r = gpp.run("""
#include <iostream>
int main() { std::cout << "from C++" << std::endl; }
""")

print(r.out)      // what the program printed
print(r.code)     // 0 when it succeeded
```

`gpp.compile(source)` checks code without running it, and `gpp.runFile(path)`
compiles a real `.cpp` file. Programs are cached by source hash, so calling
twice does not pay for `g++` twice.

## Command line

```
jaipl run FILE      run a program ('-' reads stdin)
jaipl check FILE    check syntax without running
jaipl fmt FILE      format the file in place
jaipl repl          interactive prompt
jaipl version       print the version
```

## VS Code

Install the **jaipl** extension. You get highlighting, snippets, F5 to run,
Ctrl+Shift+B to check, formatting, and errors as red squiggles.

Other editors: point your run command at `jaipl run <file>`. `jaipl check`
exits `2` on a syntax error and prints `file:line:col: message`, which is
easy to parse for linters in any editor.

## License

MIT.