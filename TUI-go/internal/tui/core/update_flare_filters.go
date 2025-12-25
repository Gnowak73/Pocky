package core

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/internal/tui/chrome"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/flares"
	"github.com/pocky/tui-go/internal/tui/styles"
	"github.com/pocky/tui-go/internal/tui/utils"
)

func (m Model) handleFlareFilterKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	// we will use type assertion with a switch statement for the flare filter option
	switch msg.String() {
	case "ctrl+c":
		return m, tea.Quit
	case "esc":
		m.Mode = ModeMain
		m.Menu.Notice = "Canceled flare filter edit"
		m.Menu.NoticeFrame = m.Frame
	case "tab", "right", "l":
		m.Filters.Focus = (m.Filters.Focus + 1) % 3
		m.Filters.FocusFrame = m.Frame
	case "left", "h":
		m.Filters.Focus--
		if m.Filters.Focus < 0 {
			m.Filters.Focus = 2
		}
		m.Filters.FocusFrame = m.Frame
	case "up", "k":
		switch m.Filters.Focus {
		case 0:
			if m.Filters.CompIdx > 0 {
				m.Filters.CompIdx--
			}
		case 1:
			if m.Filters.LetterIdx > 0 {
				m.Filters.LetterIdx--
			}
		case 2:
			if m.Filters.MagIdx > 0 {
				m.Filters.MagIdx--
			}
		}
	case "down", "j":
		switch m.Filters.Focus {
		case 0:
			if m.Filters.CompIdx < len(m.Filters.CompDisplays)-1 {
				m.Filters.CompIdx++
			}
		case 1:
			if m.Filters.LetterIdx < len(m.Filters.ClassLetters)-1 {
				m.Filters.LetterIdx++
			}
		case 2:
			if m.Filters.MagIdx < len(m.Filters.Magnitudes)-1 {
				m.Filters.MagIdx++
			}
		}
	case "enter":
		compVal := m.Filters.Comparators[m.Filters.CompIdx].Value
		letter := m.Filters.ClassLetters[m.Filters.LetterIdx]
		mag := m.Filters.Magnitudes[m.Filters.MagIdx]
		if compVal == "All" {
			m.Cfg.Comparator = "All"
			m.Cfg.FlareClass = "Any"
		} else {
			m.Cfg.Comparator = compVal
			m.Cfg.FlareClass = fmt.Sprintf("%s%s", letter, mag)
		}
		if err := config.Save(m.Cfg); err != nil {
			m.Menu.Notice = err.Error()
			m.Menu.NoticeFrame = m.Frame
			break
		}
		m.Menu.Notice = "Flare filter saved"
		m.Menu.NoticeFrame = m.Frame
		m.Mode = ModeMain
	}
	return m, nil
}

func (m Model) handleFlareFilterMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
	col, row, ok := m.optionHit(msg.X, msg.Y) // column is box, row is vertical selection
	if msg.Button == tea.MouseButtonNone && msg.Action == tea.MouseActionMotion && ok {
		m.Filters.Focus = col
	}
	switch msg.Button {
	case tea.MouseButtonWheelUp:
		switch m.Filters.Focus {
		case 0:
			if m.Filters.CompIdx > 0 {
				m.Filters.CompIdx--
			}
		case 1:
			if m.Filters.LetterIdx > 0 {
				m.Filters.LetterIdx--
			}
		case 2:
			if m.Filters.MagIdx > 0 {
				m.Filters.MagIdx--
			}
		}
	case tea.MouseButtonWheelDown:
		switch m.Filters.Focus {
		case 0:
			if m.Filters.CompIdx < len(m.Filters.CompDisplays)-1 {
				m.Filters.CompIdx++
			}
		case 1:
			if m.Filters.LetterIdx < len(m.Filters.ClassLetters)-1 {
				m.Filters.LetterIdx++
			}
		case 2:
			if m.Filters.MagIdx < len(m.Filters.Magnitudes)-1 {
				m.Filters.MagIdx++
			}
		}
	case tea.MouseButtonLeft:
		if ok && msg.Action == tea.MouseActionRelease {
			m.Filters.Focus = col
			switch col {
			case 0:
				m.Filters.CompIdx = utils.Clamp(row, 0, len(m.Filters.CompDisplays)-1)
			case 1:
				m.Filters.LetterIdx = utils.Clamp(row, 0, len(m.Filters.ClassLetters)-1)
			case 2:
				m.Filters.MagIdx = utils.Clamp(row, 0, len(m.Filters.Magnitudes)-1)
			}
		}
	}
	return m, nil
}

func (m Model) optionHit(x, y int) (col int, row int, ok bool) {
	// must be in mode and in certain area to use mouse
	if m.Mode != ModeFlareFilter || x < 0 || y < 0 {
		return 0, 0, false
	}

	cols := flares.RenderFilterColumns(m.Filters, m.Frame)
	if len(cols) != 3 { // we need magnitude, class, and comparator
		return 0, 0, false
	}

	boxLogo, versionLine, w := chrome.RenderLogoHeader(m.Width, m.Logo)
	summary := chrome.RenderSummary(m.Cfg, w)

	columns := lipgloss.JoinHorizontal(lipgloss.Top, cols...)
	title := styles.SummaryHeader.Copy().Bold(false).Render("Set Flare Filters")
	colWidth := lipgloss.Width(columns)
	if colWidth < lipgloss.Width(title) {
		colWidth = lipgloss.Width(title)
	}
	divWidth := max(colWidth, lipgloss.Width(title)+6)
	divider := lipgloss.NewStyle().Foreground(lipgloss.Color("#3A3A3A")).Render(strings.Repeat("─", divWidth))
	titleBlock := lipgloss.JoinVertical(lipgloss.Center, title, divider)
	titleBlock = lipgloss.PlaceHorizontal(colWidth, lipgloss.Center, titleBlock)

	block := lipgloss.JoinVertical(lipgloss.Left, titleBlock, "", columns)

	blockWidth := lipgloss.Width(block)
	blockHeight := lipgloss.Height(block)

	header := boxLogo + "\n" + versionLine + summary
	topY := lipgloss.Height(header) + 2

	if y < topY || y > topY+blockHeight {
		return 0, 0, false
	}

	offsetX := 0
	if w > blockWidth {
		offsetX = (w - blockWidth) / 2
	}
	if offsetX > 2 {
		offsetX -= 2
	}

	relY := y - topY
	relX := x - offsetX
	if relX < 0 {
		return 0, 0, false
	}

	titleHeight := lipgloss.Height(titleBlock) + 1
	if relY < titleHeight {
		return 0, 0, false
	}
	optY := relY - titleHeight
	col0 := cols[0]
	col1 := cols[1]
	col2 := cols[2]
	pad := 2
	colStartX := []int{0, lipgloss.Width(col0) + pad, lipgloss.Width(col0) + pad + lipgloss.Width(col1) + pad}
	colWidths := []int{lipgloss.Width(col0), lipgloss.Width(col1), lipgloss.Width(col2)}
	colIdx := -1
	for i := 0; i < 3; i++ {
		if relX >= colStartX[i] && relX < colStartX[i]+colWidths[i] {
			colIdx = i
			break
		}
	}
	if colIdx == -1 {
		return 0, 0, false
	}

	if optY < 2 {
		return 0, 0, false
	}
	rowIdx := optY - 2

	var start, window, maxRows int
	switch colIdx {
	case 0:
		window = len(m.Filters.CompDisplays)
		start = 0
		maxRows = len(m.Filters.CompDisplays)
	case 1:
		window = len(m.Filters.ClassLetters)
		start = 0
		maxRows = len(m.Filters.ClassLetters)
	case 2:
		window = 9
		maxRows = len(m.Filters.Magnitudes)
		if maxRows < window {
			window = maxRows
		}
		if maxRows > window {
			start = max(m.Filters.MagIdx-window/2, 0)
			start = min(start, maxRows-window)
		}
	default:
		return 0, 0, false
	}

	if rowIdx < 0 || rowIdx >= window {
		return 0, 0, false
	}

	actualIdx := start + rowIdx
	if actualIdx >= maxRows {
		return 0, 0, false
	}

	return colIdx, actualIdx, true
}
