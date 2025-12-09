package main

import (
	"github.com/charmbracelet/bubbles/table"
	"github.com/charmbracelet/bubbles/viewport"
	"github.com/charmbracelet/lipgloss"
)

type model struct {
	logoLines []string // string lines for logo.txt
	colored   []string // colored lines
	cfg       config
	blockW    int // column width for logo to occupy
	width     int
	height    int
	frame     int
	menuItems []string // main menu items
	selected  int
	notice    string
	noticeSet int // frame counter for notice animation

	// Modes
	mode viewMode

	// Wavelength editor
	waveOptions  []waveOption
	waveSelected map[string]bool
	waveFocus    int

	// Flare filter editor
	flareCompOptions  []string
	flareCompMap      map[string]string
	flareClassLetters []string
	flareMagnitudes   []string
	flareFocus        int // 0=comp,1=letter,2=mag
	flareCompIdx      int
	flareLetterIdx    int
	flareMagIdx       int
	flareFocusFrame   int

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

func newModel(logo []string, cfg config) model {
	// our aim is to take the lines from the logo, put them in an
	// array, and pass them through our model to color and animate them.
	// Then we will make a selectable menu and present config vars

	// first we need the visual width of the logo as drawn on the TUI,
	// measurement is in column number (terminals draw based on a grid)
	blockW := 0
	for _, l := range logo {
		blockW = max(blockW, lipgloss.Width(l))
	}

	colored := colorizeLogo(logo, blockW, 0)

	waves := defaultWaveOptions()
	selected := parseWaves(cfg.WAVE, waves)

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

	compOpts, compMap := defaultComparatorOptions()
	letters := defaultClassLetters()
	mags := defaultMagnitudes()
	compIdx, letterIdx, magIdx := parseFlareSelection(cfg, compOpts, compMap, letters, mags)

	return model{
		logoLines:         logo,
		colored:           colored,
		cfg:               cfg,
		blockW:            blockW,
		menuItems:         menu,
		mode:              modeMain,
		waveOptions:       waves,
		waveSelected:      selected,
		flareCompOptions:  compOpts,
		flareCompMap:      compMap,
		flareClassLetters: letters,
		flareMagnitudes:   mags,
		flareCompIdx:      compIdx,
		flareLetterIdx:    letterIdx,
		flareMagIdx:       magIdx,
		flareFocusFrame:   0,
		flareSelected:     make(map[int]bool),
		spinFrames:        []string{"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"},
		flareOffset:       0,
		cacheMenuItems:    cacheMenu,
		cachePick:         make(map[int]bool),
		cacheViewport:     viewport.New(80, 20),
	}
}
