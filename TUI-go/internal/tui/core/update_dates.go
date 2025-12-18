package core

import (
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/flares"
)

func (m Model) handleDateKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	handled := true
	switch msg.String() {
	case "ctrl+c":
		return m, tea.Quit
	case "esc":
		m.Mode = ModeMain
		m.Menu.Notice = "Canceled date edit"
		m.Menu.NoticeFrame = m.Frame
	case "tab", "down":
		m.Date.Focus = 1
	case "shift+tab", "up":
		m.Date.Focus = 0
	case "enter":
		start := strings.TrimSpace(m.Date.Start)
		end := strings.TrimSpace(m.Date.End)
		if start == "" {
			start = strings.TrimSpace(m.Cfg.Start)
		}
		if end == "" {
			end = strings.TrimSpace(m.Cfg.End)
		}
		if !flares.ValidDate(start) || !flares.ValidDate(end) {
			m.Menu.Notice = "Dates must be YYYY-MM-DD"
			m.Menu.NoticeFrame = m.Frame
			break
		}
		if !flares.Chronological(start, end) {
			m.Menu.Notice = "Start must be on/before End"
			m.Menu.NoticeFrame = m.Frame
			break
		}
		m.Cfg.Start = start
		m.Cfg.End = end
		if err := config.Save(m.Cfg); err != nil {
			m.Menu.Notice = err.Error()
			m.Menu.NoticeFrame = m.Frame
			break
		}
		m.Menu.Notice = "Date range saved"
		m.Menu.NoticeFrame = m.Frame
		m.Mode = ModeMain
	case "backspace", "delete":
		if m.Date.Focus == 0 {
			if len(m.Date.Start) > 0 {
				m.Date.Start = m.Date.Start[:len(m.Date.Start)-1]
			}
		} else {
			if len(m.Date.End) > 0 {
				m.Date.End = m.Date.End[:len(m.Date.End)-1]
			}
		}
	default:
		handled = false
	}
	if !handled {
		if len(msg.Runes) > 0 {
			var runes []rune
			for _, r := range msg.Runes {
				if (r >= '0' && r <= '9') || r == '-' {
					runes = append(runes, r)
				}
			}
			if len(runes) > 0 {
				target := &m.Date.Start
				if m.Date.Focus == 1 {
					target = &m.Date.End
				}
				if len(*target) < len("2006-01-02") {
					*target += string(runes)
					if len(*target) > len("2006-01-02") {
						*target = (*target)[:len("2006-01-02")]
					}
				}
			}
		}
	}
	return m, nil
}
