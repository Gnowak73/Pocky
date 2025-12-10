package main

import (
	"fmt"
	"sort"
	"strings"

	"github.com/charmbracelet/lipgloss"
)

func defaultWaveOptions() []waveOption {
	return []waveOption{
		{"94", "Fe XVIII (hot flares)"},
		{"131", "Fe VIII / Fe XXI"},
		{"171", "Fe IX (quiet corona)"},
		{"193", "Fe XII / Fe XXIV"},
		{"211", "Fe XIV (2 MK loops)"},
		{"304", "He II (chromosphere)"},
		{"335", "Fe XVI (2.5 MK)"},
		{"1600", "C IV / continuum"},
		{"1700", "continuum (photo.)"},
		{"4500", "white-light"},
	}
}

func parseWaves(val string) map[string]bool {
	// The default options are static at runtime. We don't need validation,
	// just a map which takes the values from a config (m.cfg.WAVE)
	// and then make a map where we set those values to be true. Since in go,
	// missing keys return false, we essentially have a map where slected = true
	// and unselected=false.
	selected := make(map[string]bool)
	for _, part := range strings.Split(val, ",") {
		p := strings.TrimSpace(part)
		if p != "" {
			selected[p] = true
		}
	}
	return selected
}

func buildWaveValue(opts []waveOption, sel map[string]bool) string {
	var parts []string
	for _, o := range opts {
		if sel[o.code] {
			parts = append(parts, o.code)
		}
	}
	return strings.Join(parts, ",")
}

func (m *model) toggleWave(idx int) {
	if idx < 0 || idx >= len(m.wave.options) {
		return
	}
	code := m.wave.options[idx].code
	m.wave.selected[code] = !m.wave.selected[code]
}

func waveDisplay(val string) string {
	val = strings.TrimSpace(val)
	if val == "" {
		return "<unset>"
	}

	order := []string{"94", "131", "171", "193", "211", "304", "335", "1600", "1700", "4500"}
	idx := make(map[string]int)
	for i, v := range order {
		idx[v] = i
	}

	parts := strings.Split(val, ",")
	var valid []string
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if _, ok := idx[p]; ok {
			valid = append(valid, p)
		}
	}
	if len(valid) == 0 {
		return val
	}

	sort.Slice(valid, func(i, j int) bool {
		return idx[valid[i]] < idx[valid[j]]
	})

	var out []string
	start := valid[0]
	prev := start
	for i := 1; i < len(valid); i++ {
		cur := valid[i]
		if idx[cur] == idx[prev]+1 {
			prev = cur
			continue
		}
		if start == prev {
			out = append(out, start)
		} else {
			out = append(out, fmt.Sprintf("%s-%s", start, prev))
		}
		start = cur
		prev = cur
	}
	if start == prev {
		out = append(out, start)
	} else {
		out = append(out, fmt.Sprintf("%s-%s", start, prev))
	}

	return strings.Join(out, ",")
}

func (m model) waveIndexAt(x, y int) (int, bool) {
	if m.mode != modeWavelength || y < 0 || x < 0 {
		return 0, false
	}

	content := strings.Join(m.logo.colored, "\n")
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
	editor := renderWavelengthEditor(m, w)

	header := box + "\n" + versionLine + summary
	editorTop := lipgloss.Height(header)

	lines := strings.Split(editor, "\n")
	if y < editorTop || y >= editorTop+len(lines) {
		return 0, false
	}

	relativeY := y - editorTop
	rowIdx := -1
	rowsSeen := 0
	for i := 0; i < len(lines); i++ {
		trimmed := strings.TrimSpace(lines[i])
		if trimmed == "" || strings.HasPrefix(trimmed, "space toggle") || trimmed == "Select AIA Wavelength Channels" {
			continue
		}
		if strings.Contains(trimmed, "Å") && strings.Contains(trimmed, "[") {
			if relativeY <= i-1 {
				rowIdx = rowsSeen
				break
			}
			rowsSeen++
		}
	}

	if rowIdx < 0 || rowIdx >= len(m.wave.options) {
		return 0, false
	}
	return rowIdx, true
}

func renderWavelengthEditor(m model, width int) string {
	title := summaryHeaderStyle.Copy().Bold(false).Render("Select AIA Wavelength Channels")
	divWidth := max(lipgloss.Width(title)+6, 32)
	divider := lipgloss.NewStyle().Foreground(lipgloss.Color("#3A3A3A")).Render(strings.Repeat("─", divWidth))
	titleBlock := lipgloss.JoinVertical(lipgloss.Center, title, divider)

	codeStyle := lipgloss.NewStyle().Width(6)
	descStyle := lipgloss.NewStyle()
	checkStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1"))
	focusStyle := lipgloss.NewStyle().
		Background(lipgloss.Color("#2A262A"))

	var rows []string
	for i, opt := range m.wave.options {
		check := "[ ]"
		if m.wave.selected[opt.code] {
			check = checkStyle.Render("[x]")
		}
		row := lipgloss.JoinHorizontal(
			lipgloss.Top,
			check,
			" ",
			codeStyle.Render(opt.code+"Å"),
			lightGrayStyle.Render("  │  "),
			descStyle.Render(opt.desc),
		)
		if i == m.wave.focus {
			row = focusStyle.Render(row)
		}
		rows = append(rows, row)
	}

	list := strings.Join(rows, "\n")
	list = " " + strings.ReplaceAll(list, "\n", "\n ")
	help := lightGrayStyle.Render("space toggle • ctrl+a toggle all • enter save • esc cancel")

	block := lipgloss.JoinVertical(lipgloss.Left,
		titleBlock,
		"",
		list,
	)
	indent := func(s string) string {
		return " " + strings.ReplaceAll(s, "\n", "\n ")
	}

	if width <= 0 {
		return "\n\n" + indent(block) + "\n\n\n\n\n" + indent(lipgloss.PlaceHorizontal(width, lipgloss.Center, help))
	}

	placed := lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	placed = indent(placed)
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	helpLine = indent(helpLine)
	return "\n\n" + placed + "\n\n\n\n\n" + helpLine
}
