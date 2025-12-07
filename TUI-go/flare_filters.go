package main

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/lipgloss"
)

func defaultComparatorOptions() ([]string, map[string]string) {
	opts := []string{">", "≥", "==", "≤", "<", "All"}
	m := map[string]string{
		">":   ">",
		"≥":   ">=",
		"==":  "==",
		"≤":   "<=",
		"<":   "<",
		"All": "All",
	}
	return opts, m
}

func defaultClassLetters() []string {
	return []string{"A", "B", "C", "M", "X"}
}

func defaultMagnitudes() []string {
	var mags []string
	for i := 0; i <= 9; i++ {
		for t := 0; t <= 9; t++ {
			mags = append(mags, fmt.Sprintf("%d.%d", i, t))
		}
	}
	return mags
}

func parseFlareSelection(cfg config, compOpts []string, compMap map[string]string, letters, mags []string) (int, int, int) {
	compIdx := 0
	letterIdx := 0
	magIdx := 0

	currentComp := strings.TrimSpace(cfg.COMPARATOR)
	currentClass := strings.TrimSpace(cfg.FLARE_CLASS)

	if currentComp != "" {
		for i, opt := range compOpts {
			val := compMap[opt]
			if val == "" {
				val = opt
			}
			if val == currentComp {
				compIdx = i
				break
			}
		}
	}

	if len(currentClass) >= 1 {
		letter := string(currentClass[0])
		for i, l := range letters {
			if l == letter {
				letterIdx = i
				break
			}
		}
		if len(currentClass) > 1 {
			mag := currentClass[1:]
			for i, m := range mags {
				if m == mag {
					magIdx = i
					break
				}
			}
		}
	}

	return compIdx, letterIdx, magIdx
}

func comparatorASCII(val string) string {
	val = strings.TrimSpace(val)
	switch val {
	case "≥":
		return ">="
	case "≤":
		return "<="
	case "All", "ALL":
		return "All"
	default:
		return val
	}
}

func prettyComparator(val string) string {
	val = strings.TrimSpace(val)
	if val == "" {
		return "<unset>"
	}
	switch val {
	case ">=":
		return "≥"
	case "<=":
		return "≤"
	default:
		return val
	}
}

func renderFlareColumns(m model) []string {
	headerStyle := menuHelpStyle.Copy()
	itemStyle := summaryValueStyle.Copy()
	checkStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1"))
	focusBox := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		Padding(0, 1)
	plainBox := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		Padding(0, 1)

	renderColumn := func(title string, opts []string, selected int, focused bool, window int) string {
		start := 0
		if len(opts) > window {
			start = clampInt(selected-window/2, 0, len(opts)-window)
		}
		end := minInt(len(opts), start+window)

		var rows []string
		for i := start; i < end; i++ {
			prefix := "[ ]"
			if i == selected {
				prefix = checkStyle.Render("[x]")
			}
			line := lipgloss.JoinHorizontal(lipgloss.Top, prefix, " ", itemStyle.Render(opts[i]))
			rows = append(rows, line)
		}

		headerText := headerStyle.Copy().Foreground(lipgloss.Color("#3A3A3A")).Render(title)
		if focused {
			headerAnimT := clamp(float64(maxInt(m.frame-m.flareFocusFrame, 0))/8.0, 0, 1)
			headerText = renderGradientText(
				title,
				blendHex("#7D5FFF", "#FFB7D5", headerAnimT),
				blendHex("#8B5EDB", "#F785D1", headerAnimT),
				headerStyle.Copy().Bold(true),
			)
		}

		content := lipgloss.JoinVertical(
			lipgloss.Left,
			headerText,
			"",
			strings.Join(rows, "\n"),
		)
		if focused {
			return focusBox.Copy().
				BorderForeground(lipgloss.Color("#F785D1")).
				Render(content)
		}
		return plainBox.Copy().
			BorderForeground(lipgloss.Color("#2B2B2B")).
			Render(content)
	}

	compCol := renderColumn("Comparator", m.flareCompOptions, m.flareCompIdx, m.flareFocus == 0, len(m.flareCompOptions))
	letCol := renderColumn("GOES Class", m.flareClassLetters, m.flareLetterIdx, m.flareFocus == 1, len(m.flareClassLetters))
	magCol := renderColumn("Magnitude (Scroll)", m.flareMagnitudes, m.flareMagIdx, m.flareFocus == 2, 9)

	return []string{
		lipgloss.NewStyle().PaddingRight(2).Render(compCol),
		lipgloss.NewStyle().PaddingRight(2).Render(letCol),
		magCol,
	}
}

func renderFlareEditor(m model, width int) string {
	titleStyle := summaryHeaderStyle.Copy().Bold(false)
	cols := renderFlareColumns(m)
	columns := lipgloss.JoinHorizontal(lipgloss.Top, cols...)
	title := titleStyle.Render("Set Flare Filters")
	colWidth := lipgloss.Width(columns)
	if colWidth < lipgloss.Width(title) {
		colWidth = lipgloss.Width(title)
	}
	divWidth := maxInt(colWidth, lipgloss.Width(title)+6)
	divider := lipgloss.NewStyle().Foreground(lipgloss.Color("#3A3A3A")).Render(strings.Repeat("─", divWidth))
	titleBlock := lipgloss.JoinVertical(lipgloss.Center, title, divider)
	titleBlock = lipgloss.PlaceHorizontal(colWidth, lipgloss.Center, titleBlock)

	block := lipgloss.JoinVertical(lipgloss.Left, titleBlock, "", columns)

	help := menuHelpStyle.Render("←/→/tab switch • ↑/↓ select • enter save • esc cancel")

	if width <= 0 {
		return "\n\n" + block + "\n\n" + help
	}

	placed := lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	return "\n\n" + placed + "\n\n" + helpLine
}

// flareHit identifies which column (0 comparator, 1 class, 2 magnitude) and which row is at x,y.
func (m model) flareHit(x, y int) (col int, row int, ok bool) {
	if m.mode != modeFlare || x < 0 || y < 0 {
		return 0, 0, false
	}

	cols := renderFlareColumns(m)
	if len(cols) != 3 {
		return 0, 0, false
	}

	content := strings.Join(m.colored, "\n")
	boxContent := logoBoxStyle.Render(content)
	w := m.width
	if w <= 0 {
		w = lipgloss.Width(boxContent)
	}
	box := lipgloss.Place(w, lipgloss.Height(boxContent), lipgloss.Center, lipgloss.Top, boxContent)

	boxWidth := lipgloss.Width(boxContent)
	versionText := versionStyle.Render("VERSION: 0.2")
	leftPad := 0
	if w > boxWidth {
		leftPad = (w - boxWidth) / 2
	}
	versionLine := strings.Repeat(" ", leftPad) + lipgloss.Place(boxWidth, 1, lipgloss.Right, lipgloss.Top, versionText)

	summary := renderSummary(m.cfg, w)

	columns := lipgloss.JoinHorizontal(lipgloss.Top, cols...)
	title := summaryHeaderStyle.Copy().Bold(false).Render("Set Flare Filters")
	colWidth := lipgloss.Width(columns)
	if colWidth < lipgloss.Width(title) {
		colWidth = lipgloss.Width(title)
	}
	divWidth := maxInt(colWidth, lipgloss.Width(title)+6)
	divider := lipgloss.NewStyle().Foreground(lipgloss.Color("#3A3A3A")).Render(strings.Repeat("─", divWidth))
	titleBlock := lipgloss.JoinVertical(lipgloss.Center, title, divider)
	titleBlock = lipgloss.PlaceHorizontal(colWidth, lipgloss.Center, titleBlock)

	block := lipgloss.JoinVertical(lipgloss.Left, titleBlock, "", columns)

	blockWidth := lipgloss.Width(block)
	blockHeight := lipgloss.Height(block)

	header := box + "\n" + versionLine + summary
	topY := lipgloss.Height(header) + 2

	if y < topY || y > topY+blockHeight {
		return 0, 0, false
	}

	offsetX := 0
	if w > blockWidth {
		offsetX = (w - blockWidth) / 2
	}
	if offsetX > 2 {
		offsetX -= 2
	}

	relY := y - topY
	relX := x - offsetX
	if relX < 0 {
		return 0, 0, false
	}

	titleHeight := lipgloss.Height(titleBlock) + 1
	if relY < titleHeight {
		return 0, 0, false
	}
	optY := relY - titleHeight
	col0 := cols[0]
	col1 := cols[1]
	col2 := cols[2]
	pad := 2
	colStartX := []int{0, lipgloss.Width(col0) + pad, lipgloss.Width(col0) + pad + lipgloss.Width(col1) + pad}
	colWidths := []int{lipgloss.Width(col0), lipgloss.Width(col1), lipgloss.Width(col2)}
	colIdx := -1
	for i := 0; i < 3; i++ {
		if relX >= colStartX[i] && relX < colStartX[i]+colWidths[i] {
			colIdx = i
			break
		}
	}
	if colIdx == -1 {
		return 0, 0, false
	}

	if optY < 2 {
		return 0, 0, false
	}
	rowIdx := optY - 2

	var start, window, maxRows int
	switch colIdx {
	case 0:
		window = len(m.flareCompOptions)
		start = 0
		maxRows = len(m.flareCompOptions)
	case 1:
		window = len(m.flareClassLetters)
		start = 0
		maxRows = len(m.flareClassLetters)
	case 2:
		window = 9
		maxRows = len(m.flareMagnitudes)
		if maxRows < window {
			window = maxRows
		}
		if maxRows > window {
			start = clampInt(m.flareMagIdx-window/2, 0, maxRows-window)
		}
	default:
		return 0, 0, false
	}

	if rowIdx < 0 || rowIdx >= window {
		return 0, 0, false
	}

	actualIdx := start + rowIdx
	if actualIdx >= maxRows {
		return 0, 0, false
	}

	return colIdx, actualIdx, true
}
