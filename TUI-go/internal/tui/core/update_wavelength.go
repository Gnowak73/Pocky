package core

import (
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/internal/tui/chrome"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/flares"
	"github.com/pocky/tui-go/internal/tui/styles"
)

func (m Model) handleWavelengthKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "ctrl+c":
		return m, tea.Quit
	case "ctrl+a":
		allSelected := true
		for _, opt := range m.Waves.Options {
			if !m.Waves.Selected[opt.Code] {
				allSelected = false
				break
			}
		}
		next := true
		if allSelected {
			next = false
		}
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
	}
	if msg.Button == tea.MouseButtonLeft && msg.Action == tea.MouseActionRelease {
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

	content := strings.Join(m.Logo.Colored, "\n")
	boxContent := styles.LogoBox.Render(content)

	w := m.Width
	if w <= 0 {
		w = lipgloss.Width(boxContent)
	}
	box := lipgloss.Place(w, lipgloss.Height(boxContent), lipgloss.Center, lipgloss.Top, boxContent)

	boxWidth := lipgloss.Width(boxContent)
	versionText := styles.Version.Render("VERSION: 0.2")
	leftPad := 0
	if w > boxWidth {
		leftPad = (w - boxWidth) / 2
	}
	versionLine := strings.Repeat(" ", leftPad) + lipgloss.Place(boxWidth, 1, lipgloss.Right, lipgloss.Top, versionText)

	summary := chrome.RenderSummary(m.Cfg, w)
	editor := flares.RenderWavelengthEditor(m.Waves, w)

	header := box + "\n" + versionLine + summary
	editorTop := lipgloss.Height(header)

	lines := strings.Split(editor, "\n")
	if y < editorTop || y >= editorTop+len(lines) {
		return 0, false
	}

	relativeY := y - editorTop
	rowIdx := -1
	rowsSeen := 0
	for i := 0; i < len(lines); i++ {
		trimmed := strings.TrimSpace(lines[i])
		if trimmed == "" || strings.HasPrefix(trimmed, "space toggle") || trimmed == "Select AIA Wavelength Channels" {
			continue
		}
		if strings.Contains(trimmed, "Å") && strings.Contains(trimmed, "[") {
			if relativeY <= i-1 {
				rowIdx = rowsSeen
				break
			}
			rowsSeen++
		}
	}

	if rowIdx < 0 || rowIdx >= len(m.Waves.Options) {
		return 0, false
	}
	return rowIdx, true
}
