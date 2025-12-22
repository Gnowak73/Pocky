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

	// The incoming message of FLaresLoaded holds the information on the header and entries
	// for variables to be presented in a table

	m.Selector.Loading = false
	if msg.Err != nil {
		m.Menu.Notice = msg.Err.Error()
		m.Menu.NoticeFrame = m.Frame
		m.Mode = ModeMain // go to main menu on failue, so no need for selector specific errors
		return m, nil
	}
	m.Selector.List = msg.Entries
	m.Selector.Header = msg.Header

	// we make a new selector list to ensure the previous entires are wiped out
	m.Selector.Selected = make(map[int]bool)
	if len(m.Selector.List) == 0 {
		m.Menu.Notice = "No flares found."
		m.Menu.NoticeFrame = m.Frame
		m.Mode = ModeMain
		return m, nil
	}
	m.Selector.Cursor = 0
	m.Selector.Offset = 0
	return m, nil

	// move to the View() render
}
