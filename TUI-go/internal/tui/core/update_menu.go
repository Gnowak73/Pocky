package core

// update_menu.go is responsible for wiring the Bubble Tea menu selection logic,
// so it lives in core alongside the Model and mode routing rather than in chrome.
// That keeps the state transitions, notices, and Mode switches in one place.

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/flares"
)

func (m Model) handleMenuSelection(choice string) (tea.Model, tea.Cmd) {
	switch choice {
	case "Edit Wavelength":
		m.Cache.MenuOpen = false
		m.Mode = ModeWavelength
		m.Waves.Selected = flares.ParseWaves(m.Cfg.Wave)
		m.Waves.Focus = 0
		m.Menu.Notice = ""
		m.Menu.NoticeFrame = m.Frame
	case "Edit Date Range":
		m.Cache.MenuOpen = false
		m.Mode = ModeDateRange
		m.Date.Start = ""
		m.Date.End = ""
		m.Date.Focus = 0
		m.Menu.Notice = ""
		m.Menu.NoticeFrame = m.Frame
	case "Edit Flare Class Filter":
		m.Cache.MenuOpen = false
		m.Mode = ModeFlare
		m.Filters.CompIdx, m.Filters.LetterIdx, m.Filters.MagIdx = flares.ParseFlareSelection(m.Cfg, m.Filters.Comparators, m.Filters.ClassLetters)
		m.Filters.Focus = 0
		m.Filters.FocusFrame = m.Frame
		m.Menu.Notice = ""
		m.Menu.NoticeFrame = m.Frame
	case "Select Flares":
		if strings.TrimSpace(m.Cfg.Start) == "" || strings.TrimSpace(m.Cfg.End) == "" {
			m.Menu.Notice = "Set a date range first."
			m.Menu.NoticeFrame = m.Frame
			break
		}
		if strings.TrimSpace(m.Cfg.Wave) == "" {
			m.Menu.Notice = "Select at least one wavelength first."
			m.Menu.NoticeFrame = m.Frame
			break
		}
		if strings.TrimSpace(m.Cfg.Comparator) == "" {
			m.Menu.Notice = "Set a comparator first."
			m.Menu.NoticeFrame = m.Frame
			break
		}
		m.Cache.MenuOpen = false
		m.Mode = ModeSelectFlares
		m.Selector.Loading = true
		// we will make a new selector map after the python has ran and we get the new entries.
		// m.Selector.Selected = make(map[int]bool) will thus be done in the update_flares_load
		m.Selector.Cursor = 0
		m.Selector.Offset = 0
		m.Selector.List = nil
		m.Selector.Header = ""
		m.Menu.Notice = ""
		m.Menu.NoticeFrame = 0
		return m, flares.LoadFlaresCmd(m.Cfg)
	case "Cache Options":
		m.Cache.MenuOpen = true
		m.Cache.OpenFrame = m.Frame
		m.Cache.Selected = 0
		m.Menu.Notice = ""
		m.Menu.NoticeFrame = m.Frame
	case "Quit":
		return m, tea.Quit
	default:
		m.Menu.Notice = fmt.Sprintf("Selected: %s (not implemented yet)", choice)
		m.Menu.NoticeFrame = m.Frame
	}
	return m, nil
}

func (m Model) handleCacheMenuAction(action string) (tea.Model, tea.Cmd) {
	switch action {
	case "Back":
		m.Cache.MenuOpen = false
		m.Menu.Notice = "Cache menu closed"
		m.Menu.NoticeFrame = m.Frame
	case "View Cache":
		header, rows, err := flares.LoadCache()
		m.Cache.MenuOpen = false
		if err != nil {
			header = "description\tflare_class\tstart\tend\tcoordinates\twavelength"
			rows = nil
		}
		m.Cache.Header = header
		m.Cache.Rows = rows
		m.Cache.ApplyCacheFilter("", m.Width)
		if m.Width > 0 && m.Height > 0 {
			m.Cache.Viewport.Width = max(m.Width-6, 20)
			m.Cache.Viewport.Height = max(m.Height-10, 8)
		} else {
			m.Cache.Viewport.Width = 80
			m.Cache.Viewport.Height = 20
		}
		m.Cache.Viewport.SetContent(m.Cache.Content)
		m.Mode = ModeCacheView
	case "Delete Rows":
		header, rows, err := flares.LoadCache()
		m.Cache.MenuOpen = false
		if err != nil || len(rows) == 0 {
			m.Menu.Notice = "Cache empty or missing"
			m.Menu.NoticeFrame = m.Frame
			return m, nil
		}
		m.Cache.Header = header
		m.Cache.Rows = rows
		m.Cache.ApplyCacheFilter("", m.Width)
		m.Cache.Searching = true
		m.Cache.SearchInput = ""
		m.Cache.Cursor = 0
		m.Cache.Offset = 0
		m.Cache.Pick = make(map[int]bool)
		m.Mode = ModeCacheDelete
	case "Clear Cache":
		m.Cache.MenuOpen = false
		if _, err := flares.ClearCacheFile(); err != nil {
			m.Menu.Notice = fmt.Sprintf("Clear failed: %v", err)
		} else {
			m.Menu.Notice = "Cleared flare cache"
		}
		m.Menu.NoticeFrame = m.Frame
	}
	return m, nil
}
