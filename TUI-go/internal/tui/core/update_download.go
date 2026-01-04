package core

import (
	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/chrome"
	"github.com/pocky/tui-go/internal/tui/downloads"
)

func (m Model) handleDownloadMenuSel(choice string) (tea.Model, tea.Cmd) {
	switch choice {
	case "JSOC DRMS Lvl 1":
		m.Download.Level = downloads.Level1
		m.Download.Protocol = downloads.ProtocolDRMS
		m.Mode = ModeDownloadForm
	case "JSOC DRMS Lvl 1.5":
		m.Download.Level = downloads.Level1p5
		m.Download.Protocol = downloads.ProtocolDRMS
		m.Mode = ModeDownloadForm
	case "Fido Fetch Lvl 1":
		m.Download.Level = downloads.Level1
		m.Download.Protocol = downloads.ProtocolFido
		m.Download.Form.Provider = downloads.ProviderVSO
		m.Mode = ModeDownloadForm
	case "Back":
		m.Mode = ModeMain
	}
	return m, nil
}

func (m Model) handleDownloadMenuMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
	// we reuse menu state for its premade rendering, centering, and mouse hits. Any new general
	// menu follows the exact same original recipe.
	menu := chrome.MenuState{
		Items:    m.Download.MenuItems,
		Selected: m.Download.MenuSelected,
	}

	if msg.Button == tea.MouseButtonNone && msg.Action == tea.MouseActionMotion {
		idx, ok := chrome.MenuIndexAt(
			msg.X,
			msg.Y,
			m.Width,
			m.Logo,
			m.Cfg,
			menu,
			nil, // dont use cache or frame since we dont have submenu here
			0,
		)
		if ok {
			m.Download.MenuSelected = idx
		}
	}
	switch msg.Button {
	case tea.MouseButtonWheelUp:
		if m.Download.MenuSelected > 0 {
			m.Download.MenuSelected--
		}
	case tea.MouseButtonWheelDown:
		if m.Download.MenuSelected < len(m.Download.MenuItems)-1 {
			m.Download.MenuSelected++
		}
	case tea.MouseButtonLeft:
		if msg.Action == tea.MouseActionRelease {
			return m.handleDownloadMenuSel(m.Download.MenuItems[m.Download.MenuSelected])
		}
	}
	return m, nil
}

func (m Model) handleDownloadMenuKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "ctrl+c":
		return m, tea.Quit
	case "esc":
		m.Mode = ModeMain
		return m, nil
	case "up", "k":
		if m.Download.MenuSelected > 0 {
			m.Download.MenuSelected--
		}
	case "down", "j":
		if m.Download.MenuSelected < len(m.Download.MenuItems)-1 {
			m.Download.MenuSelected++
		}
	case "enter", " ":
		if m.Download.MenuSelected >= 0 && m.Download.MenuSelected < len(m.Download.MenuItems) {
			return m.handleDownloadMenuSel(m.Download.MenuItems[m.Download.MenuSelected])
		}
	}
	return m, nil
}

func (m Model) handleDownloadFormKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	isProvider := m.Download.Protocol == downloads.ProtocolFido && m.Download.Focus == 0 // check if we can toggle

	switch msg.String() {
	case "ctrl+c":
		return m, tea.Quit
	case "esc":
		m.Mode = ModeDownloadMenu
		return m, nil
	case "up", "k":
		if m.Download.Focus > 0 {
			m.Download.Focus--
		}
	case "down", "j":
		max := len(downloads.FormLines(m.Download)) - 1
		if m.Download.Focus < max {
			m.Download.Focus++
		}
	case "backspace", "delete":
		downloads.DeleteFormChar(&m.Download, m.Download.Focus)
	case " ":
		if isProvider {
			if m.Download.Form.Provider == downloads.ProviderJSOC {
				m.Download.Form.Provider = downloads.ProviderVSO
			} else {
				m.Download.Form.Provider = downloads.ProviderJSOC
			}
			return m, nil
		}
	case "enter":
		m.Download.LastOutput = ""
		m.Download.Running = true
		m.Mode = ModeDownloadRun
		return m, downloads.RunDownloadCmd(m.Download, m.Cfg)
	default:
		if len(msg.Runes) > 0 {
			downloads.AppendFormRunes(&m.Download, m.Download.Focus, msg.Runes)
		}
	}
	return m, nil
}
