<div align="center">

[![Release](https://img.shields.io/github/v/release/Gnowak73/Pocky)](https://github.com/Gnowak73/Pocky/releases)
[![Build](https://img.shields.io/github/actions/workflow/status/Gnowak73/Pocky/go.yml?branch=main)](https://github.com/Gnowak73/Pocky/actions)
[![License](https://img.shields.io/github/license/Gnowak73/Pocky)](LICENSE)

</div>

<div align="center">
  <img src="Media/Menu.png" width="82%" />
</div>

Pocky is a Go TUI for building flare queries, downloading FITS data, and analyzing data via
machine learning and Fourier Analysis. There is a minimal bash version and a full Go version of the program.
The bash file is `pocky.sh` in the main directory. The compiled Go file is in `TUI-go/` as `pocky`.
Both can be executed with `./` after they are given sufficient permissions. On Unix systems like macOS and
Linux, `chmod +x` may be used to grant execute permissions. On Windows, it may prompt you after running
the `.exe` directly.

If there are any problems launching the executable as-is, recompile it with:

```bash
go build ./cmd/pocky
```

This requires a recent Go install for compiling. See https://go.dev/doc/install.

### Controls
Pocky is fully keyboard-driven, but also supports mouse hover, scrolling, and clicks.

- `↑/k` and `↓/j` move through menus and lists.
- `enter` selects or confirms the current item.
- `esc` or `q` goes back or cancels a screen.
- Mouse wheel scrolls in tables and viewports.
- Left click selects items and changes focus.
- If mouse input does not register, try right clicking to give the terminal focus.
  Some terminals only start sending mouse tracking events after a focus action,
  and right click is the quickest way to force that without changing selection.

### Setup and Installation
