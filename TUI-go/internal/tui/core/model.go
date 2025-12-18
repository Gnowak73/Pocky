package core

import (
	"github.com/pocky/tui-go/internal/tui/chrome"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/flares"
)

type Model struct {
	Cfg      config.Config
	Logo     chrome.LogoState
	Menu     chrome.MenuState
	Mode     ViewMode
	Waves    flares.WaveEditorState
	Filters  flares.FilterState
	Selector flares.SelectorState
	Cache    flares.CacheState
	Date     dateEditorState
	Frame    int
	Width    int
	Height   int
}

type dateEditorState struct {
	Start string
	End   string
	Focus int
}

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
