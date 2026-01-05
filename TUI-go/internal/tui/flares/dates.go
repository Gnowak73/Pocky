package flares

import (
	"strings"
	"time"

	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/styles"
)

type DateEditorState struct {
	Start string // starting date
	End   string // ending date
	Focus int    // which item we are on in the date editor
}

func RenderDateEditor(cfg config.Config, date DateEditorState, width int) string {
	valueStyle := styles.PinkOption
	focusStyle := lipgloss.NewStyle().Background(lipgloss.Color("#2A262A"))
	headerStyle := styles.LightGray
	promptStyle := styles.LightGray.Bold(true)
	ghostStyle := styles.LightGray.Faint(true)

	// val is the string of the input into the dates, palceholder is the fallback text
	renderField := func(val, placeholder string, focused bool) string {
		line := lipgloss.JoinHorizontal(
			lipgloss.Top,
			promptStyle.Render("> "), valueStyle.Render(val),
		)

		if strings.TrimSpace(val) == "" {
			if placeholder == "" {
				placeholder = "YYYY-MM-DD"
			}
			line = lipgloss.JoinHorizontal(
				lipgloss.Top,
				promptStyle.Render("> "), ghostStyle.Render(placeholder),
			)
		}
		if focused {
			return focusStyle.Render(line)
		}
		return line
	}

	startField := renderField(
		strings.TrimSpace(date.Start),
		strings.TrimSpace(cfg.Start),
		date.Focus == 0,
	)

	endField := renderField(
		strings.TrimSpace(date.End),
		strings.TrimSpace(cfg.End),
		date.Focus == 1,
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

func ValidDate(val string) bool {
	// we will check the length of the date along with time.Parse, which will
	// take a string and parse it into a time.Time value or return an error
	val = strings.TrimSpace(val)
	if val == "" {
		return false
	}
	if len(val) != len("2005-06-06") {
		return false
	}
	_, err := time.Parse("2006-01-02", val)
	return err == nil
}

func Chronological(start, end string) bool {
	// after parsing, we check if one time is after the other
	s, err1 := time.Parse("2006-01-02", start)
	e, err2 := time.Parse("2006-01-02", end)
	if err1 != nil || err2 != nil {
		return false
	}
	return !s.After(e)
}
