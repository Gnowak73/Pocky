package core

import (
	"fmt"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/flares"
)

// After we go through selector.go, we have a string for the table. All we need to do now is
// take the inputs from the mouse or keyboard and adjust the outcomes.

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
			// we flip the current selected map at the cursor to select/de-select.
			// We know this map is not nil since we zero it update_menu and update_flares_load
			m.Selector.Selected[m.Selector.Cursor] = !m.Selector.Selected[m.Selector.Cursor]
		}
	case "enter":
		if len(m.Selector.Selected) == 0 {
			// we brake if none are selected so we
			// dont try to save no flares in the following lines
			m.Menu.Notice = "No flares selected."
			m.Menu.NoticeFrame = m.Frame
			m.Mode = ModeMain
			break
		}
		err := flares.SaveFlareSelection(
			m.Selector.Header,
			m.Selector.List,
			m.Selector.Selected,
		)

		if err != nil {
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
