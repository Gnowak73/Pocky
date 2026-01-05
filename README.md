Pocky is a Go TUI for building flare queries, downloading FITS data, and analyzing data via
machine learning and Fourier Analysis. There are minimal bash and full go versions of the program.
The bash file is given as pocky.sh in the main directory. The compiled go file is in TUI-go/ as
pocky. If there are any problems with launching the executable as is, we recompile it with 
go build ./cmd/pocky for a new executable. On Unix systems (Linux/MacOS) make sure you give permission for these files to be executed with chmod +x [pocky.sh or pocky].

![Pocky Demo](Media/Menu.png)
