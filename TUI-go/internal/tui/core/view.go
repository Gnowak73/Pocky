package core

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/internal/tui/chrome"
	"github.com/pocky/tui-go/internal/tui/flares"
	"github.com/pocky/tui-go/internal/tui/styles"
)

func (m Model) View() string {
	if m.Mode == ModeCacheView {
		body := m.Cache.RenderCacheView(m.Width, m.Height)
		status := chrome.RenderStatus(statusLabel(m), "esc to quit", m.Width)

		if m.Height > 0 {
			gap := max(m.Height-lipgloss.Height(body)-lipgloss.Height(status), 0)
			return body + strings.Repeat("\n", gap) + status
		}
		return body + "\n" + status
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
	var body string
	var extraNotice string

	switch m.Mode {
	case ModeWavelength:
		body = summary + flares.RenderWavelengthEditor(m.Waves, w)
	case ModeDateRange:
		body = summary + renderDateEditor(m, w)
	case ModeFlare:
		body = summary + flares.RenderFlareEditor(m.Filters, m.Frame, w)
	case ModeSelectFlares:
		body = summary + m.Selector.Render(w)
	case ModeCacheDelete:
		body = summary + m.Cache.RenderCacheDelete(w)
	default:
		noticeLine := chrome.NoticeLine(m.Menu.Notice, m.Menu.NoticeFrame, m.Frame, w)
		if m.Cache.MenuOpen {
			body = summary + chrome.RenderMenuWithCache(w, m.Menu, cacheMenuView(m), m.Frame, noticeLine)
		} else {
			body = summary + chrome.RenderMenu(w, m.Menu, noticeLine)
		}
	}

	if m.Mode != ModeMain && m.Mode != ModeCacheView {
		if nl := chrome.NoticeLine(m.Menu.Notice, m.Menu.NoticeFrame, m.Frame, w); nl != "" {
			extraNotice = "\n" + "  " + nl
		}
	}

	status := chrome.RenderStatus(statusLabel(m), "esc to quit", m.Width)
	if m.Height > 0 {
		contentHeight := lipgloss.Height(box) + 1 + lipgloss.Height(body+extraNotice)
		gap := max(m.Height-contentHeight-lipgloss.Height(status), 0)
		return box + "\n" + versionLine + body + extraNotice + strings.Repeat("\n", gap) + status
	}

	return box + "\n" + versionLine + body + extraNotice + "\n" + status
}

func statusLabel(m Model) string {
	switch m.Mode {
	case ModeMain:
		if m.Cache.MenuOpen {
			return "Cache Options"
		}
		return "Main Menu"
	case ModeWavelength:
		return "Edit Wavelength"
	case ModeDateRange:
		return "Edit Date Range"
	case ModeFlare:
		return "Edit Flare Class Filter"
	case ModeSelectFlares:
		if m.Selector.Loading {
			return "Loading Flares..."
		}
		return "Select Flares"
	case ModeCacheView:
		return "View Cache"
	case ModeCacheDelete:
		return "Delete Cache Rows"
	default:
		return "Ready"
	}
}

func cacheMenuView(m Model) chrome.CacheMenuView {
	return chrome.CacheMenuView{
		Open:      m.Cache.MenuOpen,
		Items:     m.Cache.MenuItems,
		Selected:  m.Cache.Selected,
		OpenFrame: m.Cache.OpenFrame,
	}
}
