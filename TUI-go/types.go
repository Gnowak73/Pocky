package main

// requires pre model initialization

type comparator struct {
	display string // what user sees (unicode)
	value   string // what gets stores in config (ASCII)
}

type config struct {
	wave       string
	start      string
	end        string
	source     string
	flareClass string
	comparator string
	dlEmail    string
}

type waveOption struct {
	code string // the wavelength in Angstroms
	desc string // the side description from the select menu
}

type waveEditorState struct {
	options  []waveOption
	selected map[string]bool // map that gives true/false for options
	focus    int             // which option is highlighted in UI
}

type logoState struct {
	lines   []string // string lines for logo.txt
	colored []string // colored lines
	blockW  int      // column width for logo to occupy
}

// post model initialization
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
