package core

// view_dates.go sits in core because it renders the ModeDateRange screen using
// Model.Date/Mode and shares the same focus/notice state that the update loop
// mutates; splitting it elsewhere would force more plumbing around Model fields.

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/internal/tui/styles"
)

func renderDateEditor(m Model, width int) string {
	valueStyle := styles.PinkOption
	focusStyle := lipgloss.NewStyle().Background(lipgloss.Color("#2A262A"))
	headerStyle := styles.LightGray
	promptStyle := styles.LightGray.Bold(true)
	ghostStyle := styles.LightGray.Faint(true)

	renderField := func(val, placeholder string, focused bool) string {
		line := lipgloss.JoinHorizontal(
			lipgloss.Top,
			promptStyle.Render("> "),
			valueStyle.Render(val),
		)

		if strings.TrimSpace(val) == "" {
			if placeholder == "" {
				placeholder = "YYYY-MM-DD"
			}
			line = lipgloss.JoinHorizontal(
				lipgloss.Top,
				promptStyle.Render("> "),
				ghostStyle.Render(placeholder),
			)
		}
		if focused {
			return focusStyle.Render(line)
		}
		return line
	}

	startField := renderField(
		strings.TrimSpace(m.Date.Start),
		strings.TrimSpace(m.Cfg.Start),
		m.Date.Focus == 0,
	)
	endField := renderField(
		strings.TrimSpace(m.Date.End),
		strings.TrimSpace(m.Cfg.End),
		m.Date.Focus == 1,
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

	placed := lipgloss.Place(
		width, lipgloss.Height(block),
		lipgloss.Center, lipgloss.Top,
		block,
	)
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	combined := lipgloss.JoinVertical(lipgloss.Left, placed, "", "", helpLine)
	return "\n\n" + combined
}
