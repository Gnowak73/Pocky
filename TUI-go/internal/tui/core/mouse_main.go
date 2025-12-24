package core

import (
	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/chrome"
)

func (m Model) handleMainMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
	if m.Cache.MenuOpen {
		switch msg.Button {
		case tea.MouseButtonWheelUp:
			if m.Cache.Selected > 0 {
				m.Cache.Selected--
			}
		case tea.MouseButtonWheelDown:
			if m.Cache.Selected < len(m.Cache.MenuItems)-1 {
				m.Cache.Selected++
			}
		case tea.MouseButtonNone:
			idx, ok := chrome.CacheMenuIndexAt(
				msg.X,
				msg.Y,
				m.Width,
				m.Logo,
				m.Cfg,
				m.Menu,
				cacheMenuView(m),
				m.Frame,
			)
			if ok {
				m.Cache.Selected = idx
			}
		case tea.MouseButtonLeft:
			if msg.Action == tea.MouseActionRelease {
				return m.handleCacheMenuAction(m.Cache.MenuItems[m.Cache.Selected])
			}
		}
		return m, nil
	}

	if msg.Button == tea.MouseButtonNone && msg.Action == tea.MouseActionMotion {
		if idx, ok := chrome.CacheMenuIndexAt(msg.X, msg.Y, m.Width, m.Logo, m.Cfg, m.Menu, cacheMenuView(m), m.Frame); ok {
			m.Cache.Selected = idx
			return m, nil
		}
		if idx, ok := chrome.MenuIndexAt(msg.X, msg.Y, m.Width, m.Logo, m.Cfg, m.Menu); ok {
			m.Menu.Selected = idx
		}
	}
	switch msg.Button {
	case tea.MouseButtonWheelUp:
		if m.Menu.Selected > 0 {
			m.Menu.Selected--
		}
	case tea.MouseButtonWheelDown:
		if m.Menu.Selected < len(m.Menu.Items)-1 {
			m.Menu.Selected++
		}
	case tea.MouseButtonLeft:
		if idx, ok := chrome.MenuIndexAt(msg.X, msg.Y, m.Width, m.Logo, m.Cfg, m.Menu); ok {
			m.Menu.Selected = idx
			if msg.Action == tea.MouseActionRelease {
				return m.handleMenuSelection(m.Menu.Items[m.Menu.Selected])
			}
		}
	}
	return m, nil
}
