package main

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/styles"
)

func renderDateEditor(m model, width int) string {
	// this function will be called in view to update every time a keystroke is done
	// inside one of the inputs

	// lipgloss styles return by value
	valueStyle := styles.PinkOption
	focusStyle := lipgloss.NewStyle().Background(lipgloss.Color("#2A262A"))
	headerStyle := styles.LightGray
	promptStyle := styles.LightGray.Bold(true)
	ghostStyle := styles.LightGray.Faint(true)

	renderField := func(val, placeholder string, focused bool) string {
		line := lipgloss.JoinHorizontal(lipgloss.Top, promptStyle.Render("> "), valueStyle.Render(val))
		// if user leaves blank, we want the default value to show
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

	// val is the value as seen by the current keystrokes, placeholder is the config determined default
	startField := renderField(
		strings.TrimSpace(m.date.start),
		strings.TrimSpace(m.cfg.start),
		m.date.focus == 0,
	)
	endField := renderField(
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

	help := styles.LightGray.Render("tab switch • enter save • esc cancel")

	placed := lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	combined := lipgloss.JoinVertical(lipgloss.Left, placed, "", "", helpLine)
	return "\n\n" + combined
}
