package main

type config struct {
	Wave       string
	Start      string
	End        string
	Source     string
	FlareClass string
	Comparator string
	Dlemail    string
}

type comparator struct {
	display string // what user sees (unicode)
	value   string // what gets stores in config (ASCII)
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
