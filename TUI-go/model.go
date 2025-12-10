package main

import (
	"github.com/charmbracelet/bubbles/table"
	"github.com/charmbracelet/bubbles/viewport"
	"github.com/charmbracelet/lipgloss"
)

type model struct {
	// config
	cfg config

	// logo
	logo logoState

	// TUI window
	width  int
	height int
	frame  int

	menuItems []string // main menu items
	selected  int
	notice    string
	noticeSet int // frame counter for notice animation

	// Modes
	mode viewMode

	// Wavelength editor
	wave waveEditorState

	// Flare filter editor
	flareFilter flareFilterState

	// Flare selection
	flareList      []flareEntry
	flareHeader    string
	flareSelected  map[int]bool
	flareCursor    int
	flareOffset    int
	flareLoading   bool
	flareLoadError string
	flareTable     table.Model

	// Cache submenu
	cacheMenuOpen    bool
	cacheMenuItems   []string
	cacheSelected    int
	cacheOpenFrame   int
	cacheRows        []cacheRow
	cacheHeader      string
	cachePick        map[int]bool
	cacheCursor      int
	cacheOffset      int
	cacheViewport    viewport.Model
	cacheContent     string
	cacheFilter      string
	cacheFiltered    []cacheRow
	cacheFilterIdx   []int
	cacheSearching   bool
	cacheSearchInput string

	// Loading animation
	spinFrames []string
	spinIndex  int

	// Date editor
	dateStart string
	dateEnd   string
	dateFocus int
}

func newModel(logoLines []string, cfg config) model {
	// set defaults

	// our aim is to take the lines from the logo, put them in an
	// array, and pass them through our model to color and animate them.
	// first we need the visual width of the logo as drawn on the TUI,
	// measurement is in column number (terminals draw based on a grid)
	blockW := 0
	for _, l := range logoLines {
		blockW = max(blockW, lipgloss.Width(l))
	}
	colored := colorizeLogo(logoLines, blockW, 0)

	logoStateDefault := logoState{
		lines:   logoLines,
		colored: colored,
		blockW:  blockW,
	}

	waveStateDefault := waveEditorState{
		options:  defaultWaveOptions(),
		selected: parseWaves(cfg.wave),
	}

	comp := defaultComparator()
	letters := defaultClassLetters()
	mags := defaultMagnitudes()
	compIdx, letterIdx, magIdx := parseFlareSelection(cfg, comp, letters)

	flareFilterDefault := flareFilterState{
		comps:        comp,
		compDisplays: comparatorDisplayList(comp),
		classLetters: letters,
		magnitudes:   mags,
		compIdx:      compIdx,
		letterIdx:    letterIdx,
		magIdx:       magIdx,
		focusFrame:   0,
	}

	menu := []string{
		"Edit Wavelength",
		"Edit Date Range",
		"Edit Flare Class Filter",
		"Select Flares",
		"Cache Options",
		"Download FITS",
		"Quit",
	}
	cacheMenu := []string{
		"View Cache",
		"Delete Rows",
		"Clear Cache",
		"Back",
	}

	return model{
		logo:           logoStateDefault,
		cfg:            cfg,
		wave:           waveStateDefault,
		flareFilter:    flareFilterDefault,
		menuItems:      menu,
		mode:           modeMain,
		flareSelected:  make(map[int]bool),
		spinFrames:     []string{"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"},
		flareOffset:    0,
		cacheMenuItems: cacheMenu,
		cachePick:      make(map[int]bool),
		cacheViewport:  viewport.New(80, 20),
	}
}
