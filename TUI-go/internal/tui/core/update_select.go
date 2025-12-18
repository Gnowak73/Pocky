package core

import (
	"fmt"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/flares"
)

func (m Model) handleSelectFlaresKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "ctrl+c":
		return m, tea.Quit
	case "esc":
		m.Mode = ModeMain
		m.Menu.Notice = "Canceled flare selection"
		m.Menu.NoticeFrame = m.Frame
	case " ":
		if m.Selector.Cursor >= 0 && m.Selector.Cursor < len(m.Selector.List) {
			m.Selector.Selected[m.Selector.Cursor] = !m.Selector.Selected[m.Selector.Cursor]
		}
	case "enter":
		if len(m.Selector.Selected) == 0 {
			m.Menu.Notice = "No flares selected."
			m.Menu.NoticeFrame = m.Frame
			m.Mode = ModeMain
			break
		}
		if err := flares.SaveFlareSelection(m.Selector.Header, m.Selector.List, m.Selector.Selected); err != nil {
			m.Menu.Notice = fmt.Sprintf("Save failed: %v", err)
			m.Menu.NoticeFrame = m.Frame
		} else {
			m.Menu.Notice = fmt.Sprintf("Saved %d flares", len(m.Selector.Selected))
			m.Menu.NoticeFrame = m.Frame
		}
		m.Mode = ModeMain
	case "up", "k":
		if m.Selector.Cursor > 0 {
			m.Selector.Cursor--
		}
		m.Selector.EnsureVisible()
	case "down", "j":
		if m.Selector.Cursor < len(m.Selector.List)-1 {
			m.Selector.Cursor++
		}
		m.Selector.EnsureVisible()
	}
	return m, nil
}

func (m Model) handleSelectFlaresMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
	switch msg.Button {
	case tea.MouseButtonWheelUp:
		if m.Selector.Cursor > 0 {
			m.Selector.Cursor--
			m.Selector.EnsureVisible()
		}
	case tea.MouseButtonWheelDown:
		if m.Selector.Cursor < len(m.Selector.List)-1 {
			m.Selector.Cursor++
			m.Selector.EnsureVisible()
		}
	case tea.MouseButtonLeft:
		if msg.Action == tea.MouseActionRelease {
			if m.Selector.Cursor >= 0 && m.Selector.Cursor < len(m.Selector.List) {
				m.Selector.Selected[m.Selector.Cursor] = !m.Selector.Selected[m.Selector.Cursor]
			}
		}
	}
	return m, nil
}
