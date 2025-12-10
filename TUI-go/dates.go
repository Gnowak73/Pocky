package main

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
)

func renderDateEditor(m model, width int) string {
	valueStyle := summaryValueStyle.Copy()
	focusStyle := lipgloss.NewStyle().Background(lipgloss.Color("#2A262A"))
	headerStyle := menuHelpStyle.Copy()
	promptStyle := menuHelpStyle.Copy().Bold(true)
	ghostStyle := menuHelpStyle.Copy().Faint(true)

	renderField := func(header, val, placeholder string, focused bool) string {
		line := lipgloss.JoinHorizontal(lipgloss.Top, promptStyle.Render("> "), valueStyle.Render(val))
		if strings.TrimSpace(val) == "" {
			if placeholder == "" {
				placeholder = "YYYY-MM-DD"
			}
			line = lipgloss.JoinHorizontal(lipgloss.Top, promptStyle.Render("> "), ghostStyle.Render(placeholder))
		}
		if focused {
			return focusStyle.Render(line)
		}
		return line
	}

	startField := renderField(
		"Start date (YYYY-MM-DD) -- leave blank to remain same",
		strings.TrimSpace(m.date.start),
		strings.TrimSpace(m.cfg.start),
		m.date.focus == 0,
	)
	endField := renderField(
		"End date   (YYYY-MM-DD) -- leave blank to remain same",
		strings.TrimSpace(m.date.end),
		strings.TrimSpace(m.cfg.end),
		m.date.focus == 1,
	)

	block := lipgloss.JoinVertical(lipgloss.Left,
		headerStyle.Render("Start date (YYYY-MM-DD) -- leave blank to remain same"),
		startField,
		"",
		"",
		headerStyle.Render("End date   (YYYY-MM-DD) -- leave blank to remain same"),
		endField,
	)

	help := menuHelpStyle.Render("tab switch • enter save • esc cancel")

	indent := func(s string) string {
		return " " + strings.ReplaceAll(s, "\n", "\n ")
	}

	if width <= 0 {
		helpLine := lipgloss.PlaceHorizontal(width, lipgloss.Center, help)
		combined := lipgloss.JoinVertical(lipgloss.Left, block, "", "", helpLine)
		return "\n\n" + indent(combined)
	}

	placed := lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	placed = indent(placed)
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	helpLine = indent(helpLine)
	combined := lipgloss.JoinVertical(lipgloss.Left, placed, "", "", helpLine)
	return "\n\n" + combined
}
