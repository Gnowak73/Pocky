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

This of course requires the latest version of Go to be installed for compiling. See https://go.dev/doc/install.
