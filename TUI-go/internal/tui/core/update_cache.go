package core

import (
	"fmt"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/flares"
)

func (m Model) handleCacheViewKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "ctrl+c":
		return m, tea.Quit
	case "esc":
		m.Mode = ModeMain
		m.Menu.Notice = "Cache view closed"
		m.Menu.NoticeFrame = m.Frame
		return m, nil
	}
	var vpCmd tea.Cmd
	m.Cache.Viewport, vpCmd = m.Cache.Viewport.Update(msg)
	return m, vpCmd
}

func (m Model) handleCacheDeleteKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	if m.Cache.Searching {
		switch msg.Type {
		case tea.KeyEsc:
			m.Cache.Searching = false
			m.Cache.SearchInput = ""
			m.Cache.ApplyCacheFilter("", m.Width)
			m.Cache.EnsureCacheVisible(true)
			return m, nil
		case tea.KeyEnter:
			m.Cache.Searching = false
			m.Cache.ApplyCacheFilter(m.Cache.SearchInput, m.Width)
			m.Cache.EnsureCacheVisible(true)
			return m, nil
		case tea.KeyBackspace:
			if len(m.Cache.SearchInput) > 0 {
				m.Cache.SearchInput = m.Cache.SearchInput[:len(m.Cache.SearchInput)-1]
				m.Cache.ApplyCacheFilter(m.Cache.SearchInput, m.Width)
				m.Cache.EnsureCacheVisible(true)
			}
			return m, nil
		case tea.KeyRunes:
			m.Cache.SearchInput += msg.String()
			m.Cache.ApplyCacheFilter(m.Cache.SearchInput, m.Width)
			m.Cache.EnsureCacheVisible(true)
			return m, nil
		case tea.KeySpace:
			m.Cache.SearchInput += " "
			m.Cache.ApplyCacheFilter(m.Cache.SearchInput, m.Width)
			m.Cache.EnsureCacheVisible(true)
			return m, nil
		}
	}

	switch msg.String() {
	case "ctrl+c":
		return m, tea.Quit
	case "esc", "left":
		m.Mode = ModeMain
		m.Menu.Notice = "Canceled cache deletion"
		m.Menu.NoticeFrame = m.Frame
	case "/":
		m.Cache.Searching = true
		m.Cache.SearchInput = ""
		m.Cache.Cursor = 0
		m.Cache.Offset = 0
		return m, nil
	case "up", "k":
		if m.Cache.Cursor > 0 {
			m.Cache.Cursor--
			m.Cache.EnsureCacheVisible(true)
		}
	case "down", "j":
		rows := m.Cache.Filtered
		if rows == nil {
			rows = m.Cache.Rows
		}
		if m.Cache.Cursor < len(rows)-1 {
			m.Cache.Cursor++
			m.Cache.EnsureCacheVisible(true)
		}
	case "tab":
		rows := m.Cache.Filtered
		if rows == nil {
			rows = m.Cache.Rows
		}
		if m.Cache.Cursor >= 0 && m.Cache.Cursor < len(rows) {
			if idx := m.Cache.CacheOriginalIndex(m.Cache.Cursor); idx >= 0 {
				m.Cache.Pick[idx] = !m.Cache.Pick[idx]
			}
		}
	case "enter":
		if len(m.Cache.Pick) == 0 {
			m.Mode = ModeMain
			m.Menu.Notice = "No rows selected."
			m.Menu.NoticeFrame = m.Frame
			break
		}
		if err := flares.SaveCachePruned(m.Cache.Header, m.Cache.Rows, m.Cache.Pick); err != nil {
			m.Menu.Notice = fmt.Sprintf("Delete failed: %v", err)
		} else {
			m.Menu.Notice = fmt.Sprintf("Deleted %d rows", len(m.Cache.Pick))
			header, rows, err := flares.LoadCache()
			if err == nil {
				m.Cache.Header = header
				m.Cache.Rows = rows
				m.Cache.Pick = make(map[int]bool)
				m.Cache.ApplyCacheFilter("", m.Width)
				if m.Width > 0 && m.Height > 0 {
					m.Cache.Viewport.Width = max(m.Width-6, 20)
					m.Cache.Viewport.Height = max(m.Height-10, 8)
				}
				m.Cache.Viewport.SetContent(m.Cache.Content)
			} else {
				m.Cache.Rows = nil
				m.Cache.Pick = make(map[int]bool)
			}
		}
		m.Menu.NoticeFrame = m.Frame
		m.Mode = ModeMain
	}
	return m, nil
}

func (m Model) handleCacheDeleteMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
	switch msg.Button {
	case tea.MouseButtonWheelUp:
		if m.Cache.Cursor > 0 {
			m.Cache.Cursor--
			m.Cache.EnsureCacheVisible(true)
		}
	case tea.MouseButtonWheelDown:
		rows := m.Cache.Filtered
		if rows == nil {
			rows = m.Cache.Rows
		}
		if m.Cache.Cursor < len(rows)-1 {
			m.Cache.Cursor++
			m.Cache.EnsureCacheVisible(true)
		}
	case tea.MouseButtonLeft:
		if msg.Action == tea.MouseActionRelease {
			rows := m.Cache.Filtered
			if rows == nil {
				rows = m.Cache.Rows
			}
			if m.Cache.Cursor >= 0 && m.Cache.Cursor < len(rows) {
				if idx := m.Cache.CacheOriginalIndex(m.Cache.Cursor); idx >= 0 {
					m.Cache.Pick[idx] = !m.Cache.Pick[idx]
				}
			}
		}
	}
	return m, nil
}
