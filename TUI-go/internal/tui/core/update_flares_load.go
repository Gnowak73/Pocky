package core

import (
	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/flares"
)

func (m Model) handleFlaresLoaded(msg flares.FlaresLoadedMsg) (tea.Model, tea.Cmd) {
	m.Selector.Loading = false
	if msg.Err != nil {
		m.Selector.LoadError = msg.Err.Error()
		m.Menu.Notice = m.Selector.LoadError
		m.Menu.NoticeFrame = m.Frame
		m.Mode = ModeMain
		return m, nil
	}
	m.Selector.List = msg.Entries
	m.Selector.Header = msg.Header
	m.Selector.Selected = make(map[int]bool)
	if len(m.Selector.List) == 0 {
		m.Menu.Notice = "No flares found."
		m.Menu.NoticeFrame = m.Frame
		m.Mode = ModeMain
		return m, nil
	}
	m.Selector.Cursor = 0
	m.Selector.Offset = 0
	m.Selector.RebuildTable()
	return m, nil
}
