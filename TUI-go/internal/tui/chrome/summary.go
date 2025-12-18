package chrome

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/flares"
)

func RenderSummary(cfg config.Config, width int) string {
	rows := []struct {
		label string
		val   string
	}{
		{"Wavelength", flares.WaveDisplay(cfg.Wave)},
		{"Date Start", unsetValue(cfg.Start)},
		{"Date End", unsetValue(cfg.End)},
		{"Data Source", unsetValue(cfg.Source)},
		{"Flare Class", unsetValue(cfg.FlareClass)},
		{"Comparator", flares.PrettyComparator(cfg.Comparator)},
		{"Last Email", unsetValue(cfg.DLEmail)},
	}

	purple := lipgloss.Color("99")
	gray := lipgloss.Color("245")
	lightGray := lipgloss.Color("241")

	borderStyle := lipgloss.NewStyle().Foreground(purple)
	headerText := lipgloss.NewStyle().Foreground(purple).Bold(true)
	cellEven := lipgloss.NewStyle().Foreground(gray)
	cellOdd := lipgloss.NewStyle().Foreground(lightGray)

	pad := 1
	maxContent := lipgloss.Width("Summary")
	lineTexts := make([]string, len(rows))
	for i, row := range rows {
		line := row.label + ": " + row.val
		lineTexts[i] = line
		if w := lipgloss.Width(line); w > maxContent {
			maxContent = w
		}
	}

	cellWidth := maxContent + pad*2
	cellWidth++

	headerLine := headerText.
		Width(cellWidth).
		Align(lipgloss.Center).
		Render("SUMMARY")

	top := borderStyle.Render("┌" + strings.Repeat("─", cellWidth) + "┐")
	mid := borderStyle.Render("├" + strings.Repeat("─", cellWidth) + "┤")
	bottom := borderStyle.Render("└" + strings.Repeat("─", cellWidth) + "┘")

	var bodyLines []string
	for i, txt := range lineTexts {
		content := lipgloss.PlaceHorizontal(cellWidth, lipgloss.Left, strings.Repeat(" ", pad)+txt+strings.Repeat(" ", pad))
		styled := cellEven.Render(content)
		if i%2 == 1 {
			styled = cellOdd.Render(content)
		}
		bodyLines = append(bodyLines, borderStyle.Render("│")+styled+borderStyle.Render("│"))
	}

	tableLines := []string{
		top,
		borderStyle.Render("│") + headerLine + borderStyle.Render("│"),
		mid,
	}
	tableLines = append(tableLines, bodyLines...)
	tableLines = append(tableLines, bottom)

	tableStr := strings.Join(tableLines, "\n")
	tableWidth := lipgloss.Width(tableStr)
	w := width
	if w <= 0 {
		w = tableWidth
	}
	return "\n" + lipgloss.Place(w, len(tableLines), lipgloss.Center, lipgloss.Top, tableStr)
}

func unsetValue(val string) string {
	if strings.TrimSpace(val) == "" {
		return "<unset>"
	}
	return val
}
