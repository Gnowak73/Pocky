package core

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/internal/tui/chrome"
	"github.com/pocky/tui-go/internal/tui/flares"
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

	box, versionLine, w := chrome.RenderLogoHeader(m.Width, m.Logo)
	summary := chrome.RenderSummary(m.Cfg, w)
	var body string
	var extraNotice string

	switch m.Mode {
	case ModeWavelength:
		body = summary + flares.RenderWavelengthEditor(m.Waves, w)
	case ModeDateRange:
		body = summary + flares.RenderDateEditor(m.Cfg, m.Date, w)
	case ModeFlareFilter:
		body = summary + flares.RenderFilterEditor(m.Filters, m.Frame, w)
	case ModeSelectFlares:
		body = summary + m.Selector.Render(w)
	case ModeCacheDelete:
		body = summary + m.Cache.RenderCacheDelete(w)
	default:
		noticeLine := chrome.NoticeLine(
			m.Menu.Notice,
			m.Menu.NoticeFrame,
			m.Frame,
			w,
		)

		var cache *chrome.CacheMenuView
		if m.Cache.MenuOpen {
			c := cacheMenuView(m)
			cache = &c
		}
		// the frame is only used if the cache is non-nil anyways,
		// so we can pass m.Frame for the frame of the animation
		// without having to explicitly set it to 0 on the else case
		// for the if above.
		render := chrome.RenderMenu(
			w,
			m.Menu,
			noticeLine,
			cache,
			m.Frame,
		)

		body = summary + render

	}

	// handle notices inside of each menu
	if m.Mode != ModeMain && m.Mode != ModeCacheView {
		nl := chrome.NoticeLine(
			m.Menu.Notice,
			m.Menu.NoticeFrame,
			m.Frame,
			w,
		)
		if nl != "" {
			extraNotice = "\n\n" + "  " + nl
		}
	}

	status := chrome.RenderStatus(statusLabel(m), "esc to quit", m.Width)
	if m.Height > 0 {
		// the +1 accounts for the Versionline height
		logoHeight := lipgloss.Height(box) + 1 + lipgloss.Height(body+extraNotice)
		// we will fill a number of newlien characters between main content and status bar to
		// vertically fill the terminal
		gap := max(m.Height-logoHeight-lipgloss.Height(status), 0)
		return box + "\n" + versionLine + body + extraNotice + strings.Repeat("\n", gap) + status
	}

	return box + "\n" + versionLine + body + extraNotice + "\n" + status // without gap
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
	case ModeFlareFilter:
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
