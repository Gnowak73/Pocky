package chrome

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
	lgtbl "github.com/charmbracelet/lipgloss/table"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/flares"
	"github.com/pocky/tui-go/internal/tui/styles"
)

func unsetValue(val string) string {
	if strings.TrimSpace(val) == "" {
		return "<unset>"
	}
	return val
}

func RenderSummary(cfg config.Config, width int) string {
	rows := [][]string{
		{"Wavelength: " + flares.WaveDisplay(cfg.Wave)},
		{"Date Start: " + unsetValue(cfg.Start)},
		{"Date End: " + unsetValue(cfg.End)},
		{"Data Source: " + unsetValue(cfg.Source)},
		{"Flare Class: " + unsetValue(cfg.FlareClass)},
		{"Comparator: " + flares.PrettyComparator(cfg.Comparator)},
		{"Last Email: " + unsetValue(cfg.DLEmail)},
	}

	headerStyle := styles.Purple.Bold(true).Padding(0, 1)
	rowPadLeft := 1
	rowPadRight := 2
	cellEven := styles.Gray
	cellOdd := styles.LightGray

	t := lgtbl.New()
	t = t.Headers("SUMMARY")
	t = t.Rows(rows...)
	t = t.Border(lipgloss.NormalBorder())
	t = t.BorderStyle(styles.Purple)
	t = t.StyleFunc(func(row, col int) lipgloss.Style {
		if row == lgtbl.HeaderRow {
			return headerStyle.
				Align(lipgloss.Center)
		}
		// rows start at 0 after header
		bodyRow := row - 1
		if bodyRow%2 == 0 {
			return cellEven.Padding(0, rowPadRight, 0, rowPadLeft)
		}
		return cellOdd.Padding(0, rowPadRight, 0, rowPadLeft)
	})

	tableStr := t.String()
	tableWidth := lipgloss.Width(tableStr)
	w := width
	if w <= 0 {
		w = tableWidth
	}
	return "\n" + lipgloss.Place(
		w,
		lipgloss.Height(tableStr),
		lipgloss.Center,
		lipgloss.Top,
		tableStr,
	)
}
