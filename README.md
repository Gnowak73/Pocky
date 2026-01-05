![Pocky Demo](Media/Menu.png)
Pocky is a Go TUI for building flare queries, downloading FITS data, and analyzing data via
machine learning and Fourier Analysis. There are minimal bash and full Go versions of the program.
The bash file is `pocky.sh` in the main directory. The compiled Go file is in `TUI-go/` as `pocky`.
If there are any problems launching the executable as-is, recompile it with:

```bash
go build ./cmd/pocky
```

On Unix systems (Linux/macOS) make sure these files are executable:
```bash
chmod +x pocky.sh pocky
```


