package main

import (
	"github.com/charmbracelet/bubbles/table"
	"github.com/charmbracelet/bubbles/viewport"
)

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

type flareFilterState struct {
	comps        []comparator
	compDisplays []string // dont want to compute display list every render
	classLetters []string
	magnitudes   []string
	focus        int // 0=comp, 1=letter, 2=mag "Comp+Class+Mag"
	compIdx      int // menu index for selection
	letterIdx    int
	magIdx       int
	focusFrame   int // counter for wire box cursor animation
}

type flareSelectorState struct {
	list      []flareEntry // list which is turned into table
	header    string
	selected  map[int]bool
	cursor    int  // highlight bar which uses space to select
	offset    int  // index of first visible item in flare list
	loading   bool // loading animation bar
	loadError string
	table     table.Model
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

type cacheSubmenuState struct {
	menuOpen    bool // status of the submenu being open
	menuItems   []string
	selected    int        // index of submenu option chosen
	openFrame   int        // frame counter for submenu open animation
	rows        []cacheRow // raw cache data
	header      string
	pick        map[int]bool // the selected rows for deletion
	cursor      int
	offset      int            // index for first visible item on delete rows
	viewport    viewport.Model // view for viewing cache
	content     string         // the rendered text used by the viewport (view cache)
	filter      string
	filtered    []cacheRow
	filterIdx   []int
	searching   bool
	searchInput string
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
