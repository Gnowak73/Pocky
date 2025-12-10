package main

type config struct {
	Wave        string
	Start       string
	End         string
	Source      string
	Flare_Class string
	Comparator  string
	Dl_email    string
}

type tickMsg struct{}

type flaresLoadedMsg struct {
	entries []flareEntry
	header  string
	err     error
}

type viewMode int

const (
	modeMain viewMode = iota
	modeWavelength
	modeDateRange
	modeFlare
	modeSelectFlares
	modeCacheView
	modeCacheDelete
)

type waveOption struct {
	code string
	desc string
}

type flareEntry struct {
	desc  string
	class string
	start string
	end   string
	coord string
	full  string
}

type cacheRow struct {
	desc  string
	class string
	start string
	end   string
	coord string
	wave  string
	full  string
}
