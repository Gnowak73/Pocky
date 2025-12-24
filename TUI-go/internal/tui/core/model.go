// Package core contains the framework or "bones" of the bubbletea TUI model. This includes the
// Init -> Update -> View -> Update loop, mainly dealing with drawing the features or "limbs" together
// and passing messages
package core

import (
	"github.com/pocky/tui-go/internal/tui/chrome"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/flares"
)

type Model struct {
	Cfg  config.Config
	Logo chrome.LogoState
	Menu chrome.MenuState

	// mode is the 'screen selector', every update/view path switches or branches on the mode,
	// so it determined which key hander runs and what view is rendered. Liek a finite-state machine
	// that keeps all menus mutually exclusive.
	Mode ViewMode

	Waves    flares.WaveEditorState
	Filters  flares.FilterState
	Selector flares.SelectorState
	Cache    flares.CacheState
	Date     dateEditorState

	// TUI window
	Frame  int
	Width  int
	Height int
}

type dateEditorState struct {
	Start string
	End   string
	Focus int
}

type tickMsg struct{}

type ViewMode int

const ( // we use iota, a predeclared identifier to enumerate
	ModeMain ViewMode = iota
	ModeWavelength
	ModeDateRange
	ModeFlare
	ModeSelectFlares
	ModeCacheView
	ModeCacheDelete
)

func NewModel(logoLines []string, cfg config.Config) Model {
	logoState := chrome.NewLogoState(logoLines, 0)

	menuItems := []string{
		"Edit Wavelength",
		"Edit Date Range",
		"Edit Flare Class Filter",
		"Select Flares",
		"Cache Options",
		"Download FITS",
		"Quit",
	}

	return Model{
		Cfg:      cfg,
		Logo:     logoState,
		Menu:     chrome.MenuState{Items: menuItems},
		Mode:     ModeMain,
		Waves:    flares.NewWaveEditor(cfg),
		Filters:  flares.NewFilterState(cfg),
		Selector: flares.NewSelectorState(),
		Cache:    flares.NewCacheState(),
	}
}
