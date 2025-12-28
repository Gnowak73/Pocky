package core

import (
	"fmt"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/chrome"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/flares"
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

	// build the layour to get the height for items above the filter selection layout
	boxLogo, versionLine, w := chrome.RenderLogoHeader(m.Width, m.Logo)
	summary := chrome.RenderSummary(m.Cfg, w)
	header := boxLogo + "\n" + versionLine + summary
	block, _, _, titleHeight := flares.RenderFilterBlock(m.Filters, m.Frame)
	cols := flares.RenderFilterColumns(m.Filters, m.Frame)

	colIdx, rowIdx, hit := utils.MouseHit(utils.MouseHitSpec{
		X:      x,
		Y:      y,
		Width:  w,
		Header: header,
		Block:  block,
		TopPad: 2,
		NudgeX: 0,
		CheckX: true,
		Mapper: func(relX, relY int) (int, int, bool) {
			return flares.HitFilterColumnsRel(m.Filters, m.Frame, titleHeight, cols, relX, relY)
		},
	})
	return colIdx, rowIdx, hit
}
