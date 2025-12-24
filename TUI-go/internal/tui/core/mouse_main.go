package core

import (
	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/chrome"
)

// we will get the input as a message and output a mutated model and tea.Cmd for the
// subsequent uptake

func (m Model) handleMainMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
	// we will use type assertion with switch statements. Note
	// that tea.MouseMsg will return ints for x and y position of mouse
	// corresponding to TUI grid columns x rows
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

	// NOTE: maybe in future we combine the commmon code of scroll and left mouse button

	if msg.Button == tea.MouseButtonNone && msg.Action == tea.MouseActionMotion {
		idx, ok := chrome.MenuIndexAt(
			msg.X,
			msg.Y,
			m.Width,
			m.Logo,
			m.Cfg,
			m.Menu,
		)
		if ok {
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
		if msg.Action == tea.MouseActionRelease {
			return m.handleMenuSelection(m.Menu.Items[m.Menu.Selected])
		}

	}
	return m, nil
}
