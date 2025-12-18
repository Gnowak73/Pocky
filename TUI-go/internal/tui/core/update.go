package core

import (
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/chrome"
	"github.com/pocky/tui-go/internal/tui/flares"
)

func tick() tea.Cmd {
	return tea.Tick(time.Millisecond*80, func(time.Time) tea.Msg { return tickMsg{} })
}

func (m Model) Init() tea.Cmd {
	return tick()
}

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.Width = msg.Width
		m.Height = msg.Height
		if msg.Width > 0 && msg.Height > 0 {
			m.Cache.Viewport.Width = max(msg.Width-6, 20)
			m.Cache.Viewport.Height = max(msg.Height-10, 8)
			if m.Mode == ModeCacheView && m.Cache.Content != "" {
				m.Cache.Viewport.SetContent(m.Cache.Content)
			}
		}
	case tickMsg:
		m.Frame++
		m.Logo.Colored = chrome.ColorizeLogo(m.Logo.Lines, m.Logo.BlockW, m.Frame)
		if m.Menu.Notice != "" && m.Menu.NoticeFrame > 0 && m.Frame-m.Menu.NoticeFrame > 19 {
			m.Menu.Notice = ""
		}
		if m.Selector.Loading && len(m.Selector.Spinner.Frames) > 0 {
			m.Selector.Spinner.Index = (m.Selector.Spinner.Index + 1) % len(m.Selector.Spinner.Frames)
		}
		return m, tick()
	case flares.FlaresLoadedMsg:
		return m.handleFlaresLoaded(msg)
	case tea.KeyMsg:
		return m.handleKeyMsg(msg)
	case tea.MouseMsg:
		return m.handleMouseMsg(msg)
	}
	return m, nil
}
