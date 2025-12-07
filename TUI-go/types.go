package main

type config struct {
	WAVE        string
	START       string
	END         string
	SOURCE      string
	FLARE_CLASS string
	COMPARATOR  string
	DL_EMAIL    string
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
