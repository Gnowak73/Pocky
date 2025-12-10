package main

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/lucasb-eyer/go-colorful"
)

func renderStatus(m model) string {
	w := m.width
	if w <= 0 {
		w = 0
	}

	statusLabel := func() string {
		switch m.mode {
		case modeMain:
			if m.cache.menuOpen {
				return " Cache Options"
			}
			return " Main Menu"
		case modeWavelength:
			return " Edit Wavelength"
		case modeDateRange:
			return " Edit Date Range"
		case modeFlare:
			return " Edit Flare Class Filter"
		case modeSelectFlares:
			if m.flare.sel.loading {
				return " Loading Flares..."
			}
			return " Select Flares"
		case modeCacheView:
			return " View Cache"
		case modeCacheDelete:
			return " Delete Cache Rows"
		default:
			return " Ready"
		}
	}()

	statusKey := statusKeyStyle.Render("POCKY")
	statusArrow := statusArrowStyle.
		Foreground(statusBarStyle.GetBackground()).
		Background(statusKeyStyle.GetBackground()).
		Render("")
	infoBox := statusTextStyle.Render(statusLabel)
	available := max(w-lipgloss.Width(statusKey)-lipgloss.Width(statusArrow)-lipgloss.Width(infoBox), 0)
	hints := renderStaticGradientHint("esc to quit", available)

	bar := lipgloss.JoinHorizontal(
		lipgloss.Top,
		statusKey,
		statusArrow,
		infoBox,
		hints,
	)

	if w > 0 {
		return statusBarStyle.Width(w).Render(bar)
	}
	return statusBarStyle.Render(bar)
}

func renderStaticGradientHint(text string, available int) string {
	if available <= 0 {
		return ""
	}

	runes := []rune(text)
	if len(runes) == 0 {
		return ""
	}

	start, err := colorful.Hex("#D147FF")
	if err != nil {
		start = colorful.Color{}
	}
	end, err := colorful.Hex("#8B5EDB")
	if err != nil {
		end = colorful.Color{}
	}

	charStyle := statusHintStyle.Copy().Padding(0)
	var parts []string
	steps := len(runes)
	for i, r := range runes {
		t := 0.0
		if steps > 1 {
			t = float64(i) / float64(steps-1)
		}
		col := start.BlendHcl(end, t)
		parts = append(parts, charStyle.Foreground(lipgloss.Color(col.Hex())).Render(string(r)))
	}

	colored := strings.Join(parts, "")
	return statusHintStyle.Copy().
		Width(available).
		Align(lipgloss.Right).
		Render(colored)
}

// noticeLine generates the transient banner shown below editors, selectors, and the menu.
// It intentionally does not directly render itself: callers (renderMenu/renderMenuWithCache and View)
// append its output in place to keep the notice centered above the status bar.
func (m model) noticeLine(width int) string {
	if m.menu.notice == "" {
		return ""
	}
	if m.menu.noticeFrame <= 0 {
		return ""
	}
	elapsed := m.frame - m.menu.noticeFrame
	const hold = 10
	const life = 19
	if elapsed >= life {
		return ""
	}
	t := 0.0
	if elapsed > hold {
		t = clamp(float64(elapsed-hold)/float64(life-hold), 0, 1)
	}
	col := blendHex("#FF6B81", "#353533", t)
	text := lipgloss.NewStyle().Foreground(lipgloss.Color(col)).Render(m.menu.notice)
	widthTarget := width
	if widthTarget <= 0 {
		widthTarget = lipgloss.Width(text)
	}
	return lipgloss.Place(widthTarget, 1, lipgloss.Center, lipgloss.Top, text)
}

// renderProgress draws a simple horizontal progress bar.
func renderProgress(current, total, width int) string {
	if width < 10 {
		width = 10
	}
	if total <= 0 {
		total = 1
	}
	if current < 0 {
		current = 0
	}
	if current > total {
		current = total
	}
	percent := float64(current) / float64(total)
	fillCount := int(percent * float64(width))
	if fillCount > width {
		fillCount = width
	}
	filled := strings.Repeat("█", fillCount)
	empty := strings.Repeat("─", max(width-fillCount, 0))
	label := fmt.Sprintf(" %3.0f%%", percent*100)
	bar := filled + empty
	if len(label) <= len(bar) {
		bar = bar[:len(bar)-len(label)] + label
	} else {
		bar += label
	}
	return lightGrayStyle.Render(bar)
}
