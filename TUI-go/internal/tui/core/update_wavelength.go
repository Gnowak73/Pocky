package core

import (
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/internal/tui/chrome"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/flares"
)

func (m Model) handleWavelengthKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "ctrl+c":
		return m, tea.Quit
	case "ctrl+a":
		// ParseWaves always returns a map, and selected wave is reliably set
		// from NewWaveEditor and on wavelength editor entry, so waves.selected is never nil
		total := len(m.Waves.Options)
		selected := 0
		for _, opt := range m.Waves.Options {
			if m.Waves.Selected[opt.Code] {
				selected++
			}
		}
		next := selected != total
		for _, opt := range m.Waves.Options {
			m.Waves.Selected[opt.Code] = next
		}
	case "esc":
		m.Mode = ModeMain
		m.Menu.Notice = "Canceled wavelength edit"
		m.Menu.NoticeFrame = m.Frame
	case "up", "k":
		if m.Waves.Focus > 0 {
			m.Waves.Focus--
		}
	case "down", "j":
		if m.Waves.Focus < len(m.Waves.Options)-1 {
			m.Waves.Focus++
		}
	case " ":
		m.Waves.Toggle(m.Waves.Focus)
	case "enter":
		m.Cfg.Wave = flares.BuildWaveValue(m.Waves.Options, m.Waves.Selected)
		if err := config.Save(m.Cfg); err != nil {
			m.Menu.Notice = err.Error()
			m.Menu.NoticeFrame = m.Frame
		} else {
			m.Menu.Notice = "Wavelength saved"
			m.Menu.NoticeFrame = m.Frame
		}
		m.Mode = ModeMain
	}
	return m, nil
}

func (m Model) handleWavelengthMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
	if msg.Button == tea.MouseButtonNone && msg.Action == tea.MouseActionMotion {
		if idx, ok := m.waveIndexAt(msg.X, msg.Y); ok {
			m.Waves.Focus = idx
		}
	} else if msg.Button == tea.MouseButtonLeft && msg.Action == tea.MouseActionRelease {
		if idx, ok := m.waveIndexAt(msg.X, msg.Y); ok {
			m.Waves.Focus = idx
			m.Waves.Toggle(idx)
		}
	}
	return m, nil
}

func (m Model) waveIndexAt(x, y int) (int, bool) {
	if m.Mode != ModeWavelength || y < 0 || x < 0 {
		return 0, false
	}

	boxLogo, versionLine, w := chrome.RenderLogoHeader(m.Width, m.Logo)
	summary := chrome.RenderSummary(m.Cfg, w)
	header := boxLogo + "\n" + versionLine + summary
	editorTop := lipgloss.Height(header)
	return flares.HitWavelengthRow(m.Waves, w, x, y-editorTop)
}
