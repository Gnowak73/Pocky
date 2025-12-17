package main

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/styles"
)

func (m model) View() string {
	// post update, we go to the view to render

	if m.mode == modeCacheView {
		body := renderCacheView(m, m.width)
		status := renderStatus(m)

		// if we have height, we make a gap to push the status bar to the bottom
		// by adding enough lines between body and status to prevent short window problems
		if m.height > 0 {
			gap := max(m.height-lipgloss.Height(body)-lipgloss.Height(status), 0)
			return body + strings.Repeat("\n", gap) + status
		}
		return body + "\n" + status
	}

	content := strings.Join(m.logo.colored, "\n")
	boxContent := styles.LogoBox.Render(content)

	w := m.width
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

	summary := renderSummary(m.cfg, w)
	var body string
	// extraNotice captures noticeLine output for modes other than the main menu.
	// The main menu already renders its own notice via renderMenu/renderMenuWithCache,
	// so we use extraNotice for non-main messages
	var extraNotice string
	switch m.mode {
	case modeWavelength:
		body = summary + renderWavelengthEditor(m, w)
	case modeDateRange:
		body = summary + renderDateEditor(m, w)
	case modeFlare:
		body = summary + renderFlareEditor(m, w)
	case modeSelectFlares:
		body = summary + renderSelectFlares(m, w)
	case modeCacheView:
		body = renderCacheView(m, w)
	case modeCacheDelete:
		body = renderCacheDelete(m, w)
	default:
		if m.cache.menuOpen {
			body = summary + renderMenuWithCache(m, w)
		} else {
			body = summary + renderMenu(m, w)
		}
	}
	if m.mode != modeMain && m.mode != modeCacheView {
		if nl := m.noticeLine(w); nl != "" {
			extraNotice = "\n" + "  " + nl
		}
	}

	status := renderStatus(m)
	if m.height > 0 {
		contentHeight := lipgloss.Height(box) + 1 + lipgloss.Height(body+extraNotice)
		gap := max(m.height-contentHeight-lipgloss.Height(status), 0)
		return box + "\n" + versionLine + body + extraNotice + strings.Repeat("\n", gap) + status
	}

	return box + "\n" + versionLine + body + extraNotice + "\n" + status
}
