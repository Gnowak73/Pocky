package chrome

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/lucasb-eyer/go-colorful"
	"github.com/pocky/tui-go/internal/tui/styles"
	"github.com/pocky/tui-go/internal/tui/theme"
)

func RenderStatus(label string, hint string, width int) string {
	// we now aim to render the ltitle marker line on the bottom telling
	// us which menu we are in etc.
	statusKey := styles.StatusKey.Render("POCKY")
	statusArrow := styles.StatusArrow.
		Foreground(styles.StatusBar.GetBackground()).
		Background(styles.StatusKey.GetBackground()).
		Render("")

	infoBox := styles.StatusText.Render(" " + label)

	// the effective available width will be the entire size of the terminal minus
	// the left-hand side text for the program nad the menu we are in
	lhs := lipgloss.Width(statusKey) - lipgloss.Width(statusArrow) - lipgloss.Width(infoBox)
	available := max(width-lhs, 0)
	hints := renderStaticGradient(hint, available)

	bar := lipgloss.JoinHorizontal(
		lipgloss.Top,
		statusKey,
		statusArrow,
		infoBox,
		hints,
	)

	if width > 0 {
		return styles.StatusBar.Width(width).Render(bar)
	}
	return styles.StatusBar.Render(bar)
}

func renderStaticGradient(text string, available int) string {
	if available <= 0 {
		return ""
	}

	runes := []rune(text) // use runes in case of misaligned byte array
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

	charStyle := styles.StatusHint.Padding(0) // ensure no margins or padding
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
	return styles.StatusHint.
		Width(available).
		Align(lipgloss.Right).
		Render(colored) // because styles are immutable this is a copy
}

func NoticeLine(notice string, noticeFrame, frame, width int) string {
	if notice == "" || noticeFrame <= 0 {
		return ""
	}
	elapsed := frame - noticeFrame
	const hold = 10
	const life = 19
	if elapsed >= life {
		return ""
	}
	// after 10 frames we begin fading animation
	t := 0.0
	if elapsed > hold {
		t = theme.Clamp(float64(elapsed-hold)/float64(life-hold), 0, 1)
	}
	col := theme.BlendHex("#FF6B81", "#353533", t)
	text := lipgloss.NewStyle().Foreground(lipgloss.Color(col)).Render(notice)

	widthTarget := width
	if widthTarget <= 0 {
		widthTarget = lipgloss.Width(text)
	}
	return lipgloss.Place(widthTarget, 1, lipgloss.Center, lipgloss.Top, text)
}

func RenderProgress(current, total, width int) string { // NOTE: currently not used
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
	fillCount = max(fillCount, width)
	filled := strings.Repeat("█", fillCount)
	empty := strings.Repeat("─", max(width-fillCount, 0))
	label := fmt.Sprintf(" %3.0f%%", percent*100)
	bar := filled + empty
	if len(label) <= len(bar) {
		bar = bar[:len(bar)-len(label)] + label
	} else {
		bar += label
	}
	return styles.LightGray.Render(bar)
}
