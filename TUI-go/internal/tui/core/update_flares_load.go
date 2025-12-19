package core

import (
	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/flares"
)

func (m Model) handleFlaresLoaded(msg flares.FlaresLoadedMsg) (tea.Model, tea.Cmd) {
	// we need to take in the mesage for flares loaded, then return a model that is ready
	// to select flares from the loaded table along with giving back a tea.Cmd which will
	// run, return a new tea.Msg, and we go back into the cycle of update() -> mutate -> render.
	// Here, we mutate.

	m.Selector.Loading = false
	if msg.Err != nil {
		m.Menu.Notice = msg.Err.Error()
		m.Menu.NoticeFrame = m.Frame
		m.Mode = ModeMain // go to main menu on failue, so no need for selector specific errors
		return m, nil
	}
	m.Selector.List = msg.Entries
	m.Selector.Header = msg.Header

	// we need to know which flares are selected, use a map with bool value for chosen or not
	m.Selector.Selected = make(map[int]bool)
	if len(m.Selector.List) == 0 {
		m.Menu.Notice = "No flares found."
		m.Menu.NoticeFrame = m.Frame
		m.Mode = ModeMain
		return m, nil
	}
	m.Selector.Cursor = 0
	m.Selector.Offset = 0
	m.Selector.RebuildTable() // make the table!
	return m, nil

	// move to the View() render
}
