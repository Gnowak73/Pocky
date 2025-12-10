package main

import (
	"github.com/charmbracelet/bubbles/viewport"
	"github.com/charmbracelet/lipgloss"
)

type model struct {
	cfg     config
	logo    logoState
	menu    menuState
	mode    viewMode
	wave    waveEditorState
	flare   flareState // flare selector and filter
	cache   cacheSubmenuState
	spinner spinnerState
	date    dateEditorState

	// TUI window
	width  int
	height int
	frame  int
}

func newModel(logoLines []string, cfg config) model {
	// set defaults

	blockW := 0
	for _, l := range logoLines {
		// the visual width of the logo as drawn by the TUI, measured
		// as column number (terminal draws based on grid)
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

	comps := defaultComparator()
	letters := defaultClassLetters()
	mags := defaultMagnitudes()
	compIdx, letterIdx, magIdx := parseFlareSelection(cfg, comps, letters)

	flareFilterDefault := flareFilterState{
		comps:        comps,
		compDisplays: comparatorDisplayList(comps),
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

	flareDefault := flareState{
		filter: flareFilterDefault,
		sel:    flareSelectorDefault,
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

	items := []string{
		"Edit Wavelength",
		"Edit Date Range",
		"Edit Flare Class Filter",
		"Select Flares",
		"Cache Options",
		"Download FITS",
		"Quit",
	}

	menuDefault := menuState{
		items: items,
	}

	return model{
		logo:    logoDefault,
		cfg:     cfg,
		wave:    waveDefault,
		flare:   flareDefault,
		menu:    menuDefault,
		mode:    modeMain,
		spinner: spinnerDefault,
		date:    dateEditorDefault,
		cache:   cacheSubmenuDefault,
	}
}
