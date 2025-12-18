package flares

import (
	"fmt"
	"sort"
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/styles"
)

type WaveOption struct {
	Code string
	Desc string
}

type WaveEditorState struct {
	Options  []WaveOption
	Selected map[string]bool
	Focus    int
}

func NewWaveEditor(cfg config.Config) WaveEditorState {
	return WaveEditorState{
		Options:  DefaultWaveOptions(),
		Selected: ParseWaves(cfg.Wave),
	}
}

func DefaultWaveOptions() []WaveOption {
	return []WaveOption{
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

func ParseWaves(val string) map[string]bool {
	selected := make(map[string]bool)
	for _, part := range strings.Split(val, ",") {
		p := strings.TrimSpace(part)
		if p != "" {
			selected[p] = true
		}
	}
	return selected
}

func BuildWaveValue(opts []WaveOption, sel map[string]bool) string {
	var parts []string
	for _, o := range opts {
		if sel[o.Code] {
			parts = append(parts, o.Code)
		}
	}
	return strings.Join(parts, ",")
}

func (w *WaveEditorState) Toggle(idx int) {
	if idx < 0 || idx >= len(w.Options) {
		return
	}
	code := w.Options[idx].Code
	w.Selected[code] = !w.Selected[code]
}

func WaveDisplay(val string) string {
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

func RenderWavelengthEditor(state WaveEditorState, width int) string {
	title := styles.SummaryHeader.Copy().Bold(false).Render("Select AIA Wavelength Channels")
	divWidth := max(lipgloss.Width(title)+6, 32)
	divider := lipgloss.NewStyle().Foreground(lipgloss.Color("#3A3A3A")).Render(strings.Repeat("─", divWidth))
	titleBlock := lipgloss.JoinVertical(lipgloss.Center, title, divider)

	codeStyle := lipgloss.NewStyle().Width(6)
	descStyle := lipgloss.NewStyle()
	checkStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1"))
	focusStyle := lipgloss.NewStyle().
		Background(lipgloss.Color("#2A262A"))

	var rows []string
	for i, opt := range state.Options {
		check := "[ ]"
		if state.Selected[opt.Code] {
			check = checkStyle.Render("[x]")
		}
		row := lipgloss.JoinHorizontal(
			lipgloss.Top,
			check,
			" ",
			codeStyle.Render(opt.Code+"Å"),
			styles.LightGray.Render("  │  "),
			descStyle.Render(opt.Desc),
		)
		if i == state.Focus {
			row = focusStyle.Render(row)
		}
		rows = append(rows, row)
	}

	list := strings.Join(rows, "\n")
	list = " " + strings.ReplaceAll(list, "\n", "\n ")
	help := styles.LightGray.Render("space toggle • ctrl+a toggle all • enter save • esc cancel")

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
