package core

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/internal/tui/chrome"
	"github.com/pocky/tui-go/internal/tui/downloads"
	"github.com/pocky/tui-go/internal/tui/flares"
)

// Update() copies the model but it also returns it. This is how it mutates the model, NOT by using
// a pointer and mutating the original mode. View does not return anything, so it only takes in copies of
// the model. Hence, any changes done during view will not permanently affect the model.

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

	// we return the width from the logoheader, which computes the effective width of the logo block
	// (it falls back to the logo's width if m.width is 0 or too small). We reuse that width so the
	// summmary/menu/editor lines align to the logo block, not just the full terminal width.
	logoBox, versionLine, w := chrome.RenderLogoHeader(m.Width, m.Logo)
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
	case ModeDownloadMenu:
		menu := chrome.MenuState{
			Items:    m.Download.MenuItems,
			Selected: m.Download.MenuSelected,
		}
		noticeLine := chrome.NoticeLine(
			m.Menu.Notice,
			m.Menu.NoticeFrame,
			m.Frame,
			w,
		)
		body = summary + chrome.RenderMenu(w, menu, noticeLine, nil, m.Frame)
	case ModeDownloadForm:
		body = downloads.RenderForm(m.Download, w)
	case ModeDownloadRun:
		body = summary + downloads.RenderRun(m.Download, w)
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
		logoHeight := lipgloss.Height(logoBox) + 1 + lipgloss.Height(body+extraNotice)
		// we will fill a number of newlien characters between main content and status bar to
		// vertically fill the terminal
		gap := max(m.Height-logoHeight-lipgloss.Height(status), 0)
		return logoBox + "\n" + versionLine + body + extraNotice + strings.Repeat("\n", gap) + status
	}

	return logoBox + "\n" + versionLine + body + extraNotice + "\n" + status // without gap
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
	case ModeDownloadMenu:
		return "Download FITs"
	case ModeDownloadForm:
		return "Download FITs Form"
	case ModeDownloadRun:
		return "Downloading..."
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
