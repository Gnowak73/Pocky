package core

import (
	tea "github.com/charmbracelet/bubbletea"
)

func (m Model) handleMainKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	if m.Cache.MenuOpen {
		switch msg.String() {
		case "ctrl+c":
			return m, tea.Quit
		case "esc", "left":
			m.Cache.MenuOpen = false
			return m, nil
		case "up", "k":
			if m.Cache.Selected > 0 {
				m.Cache.Selected--
			}
			return m, nil
		case "down", "j":
			if m.Cache.Selected < len(m.Cache.MenuItems)-1 {
				m.Cache.Selected++
			}
			return m, nil
		case "enter", " ":
			if m.Cache.Selected >= 0 && m.Cache.Selected < len(m.Cache.MenuItems) {
				return m.handleCacheMenuAction(m.Cache.MenuItems[m.Cache.Selected])
			}
			return m, nil
		}
	}

	switch msg.String() {
	case "ctrl+c", "esc":
		return m, tea.Quit
	case "up", "k":
		if m.Menu.Selected > 0 {
			m.Menu.Selected--
		}
	case "down", "j":
		if m.Menu.Selected < len(m.Menu.Items)-1 {
			m.Menu.Selected++
		}
	case "enter", " ":
		if m.Menu.Selected >= 0 && m.Menu.Selected < len(m.Menu.Items) {
			return m.handleMenuSelection(m.Menu.Items[m.Menu.Selected])
		}
	}
	return m, nil
}
