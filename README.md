# jaipl

A small language that runs anywhere.

```jai
class Dog {
    let name
    func new(name) { self.name = name }
    func speak() { return self.name + " says woof" }
}

print(new Dog("Rex").speak())
```

## Install

Linux and macOS:

```sh
curl -fsSL https://jaivardhanpandey66-create.github.io/jaipl/install.sh | sh
```

Windows: download the installer from the same site. Nothing needs to be
preinstalled; the installer bundles Python.

From a checkout:

```sh
./install.sh --local .
```

## Commands

| Command | What it does |
| --- | --- |
| `jaipl run FILE.jai` | run a program |
| `jaipl check FILE.jai` | syntax check, with line and column |
| `jaipl fmt FILE.jai` | format in place, refusing unsafe rewrites |
| `jaipl repl` | interactive prompt |
| `jaipl version` | print the version |

## Layout

- `arcide/jaipl/` — lexer, parser, interpreter, C++ bridge, CLI
- `examples/` — sample programs
- `install.sh` — Linux and macOS installer
- `jaipl-site/` — the web site, deployed by GitHub Pages

## Editor support

```sh
code --install-extension jaipl.jaipl
```

Other editors only need `jaipl run <file>` in their run command.

MIT licensed.
