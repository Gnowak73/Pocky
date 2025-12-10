package main

import (
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
	flareSelector flareSelectorState

	// Cache submenu
	cache cacheSubmenuState

	// Loading animation
	spinner spinnerState

	// Date editor
	date dateEditorState
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

	logoDefault := logoState{
		lines:   logoLines,
		colored: colored,
		blockW:  blockW,
	}

	waveDefault := waveEditorState{
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

	flareSelectorDefault := flareSelectorState{
		selected: make(map[int]bool),
		offset:   0,
	}

	cacheMenu := []string{
		"View Cache",
		"Delete Rows",
		"Clear Cache",
		"Back",
	}

	cacheSubmenuDefault := cacheSubmenuState{
		menuItems: cacheMenu,
		pick:      make(map[int]bool),
		viewport:  viewport.New(80, 20),
	}

	dateEditorDefault := dateEditorState{}

	spinnerDefault := spinnerState{
		frames: []string{"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"},
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

	return model{
		logo:          logoDefault,
		cfg:           cfg,
		wave:          waveDefault,
		flareFilter:   flareFilterDefault,
		menuItems:     menu,
		mode:          modeMain,
		flareSelector: flareSelectorDefault,
		spinner:       spinnerDefault,
		date:          dateEditorDefault,
		cache:         cacheSubmenuDefault,
	}
}
