package flares

import (
	"fmt"
	"sort"
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/styles"
	"github.com/pocky/tui-go/internal/tui/utils"
)

type WaveOption struct {
	Code string // the wavelength identifier (the wavelength in Angstroms)
	Desc string // the human-readable description for that channel
}

type WaveEditorState struct {
	Options  []WaveOption    // slice of options for the menu
	Selected map[string]bool // map designating selected options, map [code] -> bool
	Focus    int             // which row we are focused on in the table for selection
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
	// after separating the wavelengths by their commas (from the config),
	// we will trim all leading/trailing whitespaces and then check if the
	// result is empty. If not, we have a valid result which we mark as selected
	// in a map. We return this map, which will be used to preselect our saved
	// cache options in the wavelength selection menu
	for _, part := range strings.Split(val, ",") {
		p := strings.TrimSpace(part)
		if p != "" {
			selected[p] = true
		}
	}
	return selected
}

func NewWaveEditor(cfg config.Config) WaveEditorState {
	return WaveEditorState{
		Options:  DefaultWaveOptions(),
		Selected: ParseWaves(cfg.Wave),
	}
}

func BuildWaveValue(opts []WaveOption, sel map[string]bool) string {
	// we want to build a config string from the selected wwavelength codes.
	// We verify if a key exists in the map. If so, we append that code to a slice
	// of strings and return the final result as a string separated by commas.
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

func HitWavelengthRow(state WaveEditorState, width int, x, y int) (int, bool) {
	// We want to map mouse coordinates relative to the wavelength editor block to a row
	// index in the options list, matching the layout used in RenderWavelengthEditor.
	if x < 0 || y < 0 {
		return 0, false
	}

	block, rowStart := renderWavelengthBlock(state)
	_, row, ok := utils.MouseHit(utils.MouseHitSpec{
		X:        x,
		Y:        y,
		Width:    width,
		Header:   "",
		Block:    block,
		TopPad:   0,
		NudgeX:   1, // we padd the left side for the options by 1, so we account for the nudge
		CheckX:   true,
		RowStart: rowStart,
		RowCount: len(state.Options),
	})
	return row, ok
}

func WaveDisplay(val string) string {
	// we will take the input of comma separated wavelengths from the config
	// and output a nice looking display for the wvelengths that uses dashes - in between subsequent
	// orders, like 1-5 instead of 1,2,3,4,5
	val = strings.TrimSpace(val)
	if val == "" {
		return "<unset>"
	}

	// if we make a map from each wavelength to an index (representing its position), so that we can
	// order the wavelengths from least to greatest (or canonical order).
	opts := DefaultWaveOptions()
	order := make([]string, 0, len(opts)) // the slice of strings for code options like "171"
	for _, opt := range opts {
		order = append(order, opt.Code)
	}
	idx := make(map[string]int) // maps code (string) to position
	for i, v := range order {
		idx[v] = i
	}

	parts := strings.Split(val, ",")
	var valid []string // the slice of codes from the input that exist in order
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if _, ok := idx[p]; ok {
			valid = append(valid, p)
		}
	}
	if len(valid) == 0 {
		return val
	}

	// order by least positions
	sort.Slice(valid, func(i, j int) bool {
		return idx[valid[i]] < idx[valid[j]]
	})

	var out []string
	start := valid[0] // assumes non-empty
	prev := start
	for i := 1; i < len(valid); i++ {
		cur := valid[i]

		// if current code is consecutive, extend the run
		if idx[cur] == idx[prev]+1 {
			prev = cur
			continue
		}

		// if there is a gap, either append single code or a range, then start a new run
		if start == prev { // then current range has only one item
			out = append(out, start)
		} else { // then there is a range of values
			out = append(out, fmt.Sprintf("%s-%s", start, prev))
		}
		start = cur
		prev = cur
	}

	// outside for statement for last loop since we only flush a range when we hit a break.
	// If final run ends without a break, we wont flush out the last run properly in the loop.
	if start == prev {
		out = append(out, start)
	} else {
		out = append(out, fmt.Sprintf("%s-%s", start, prev))
	}

	return strings.Join(out, ",") // join contiguous runs by commas
}

func RenderWavelengthEditor(state WaveEditorState, width int) string {
	// given the state and the width, we will return the rendered string
	block, _ := renderWavelengthBlock(state)
	help := styles.LightGray.Render("space toggle • ctrl+a toggle all • enter save • esc cancel")
	gap := strings.Repeat("\n", 5)

	if width <= 0 {
		return "\n\n" + block + gap + lipgloss.PlaceHorizontal(width, lipgloss.Center, help)
	}

	placed := lipgloss.Place(
		width,
		lipgloss.Height(block),
		lipgloss.Center,
		lipgloss.Top,
		block,
	)
	helpLine := lipgloss.Place(
		width,
		1,
		lipgloss.Center,
		lipgloss.Top,
		help,
	)

	return "\n\n" + placed + gap + helpLine
}

func renderWavelengthBlock(state WaveEditorState) (string, int) {
	title := styles.SummaryHeader.Bold(false).Render("Select AIA Wavelength Channels")

	// the width for the divider will be slightly larger than the title by 6 but no less than 32
	divWidth := max(lipgloss.Width(title)+6, 32)
	divider := lipgloss.NewStyle().
		Foreground(lipgloss.Color("#3A3A3A")).Render(strings.Repeat("─", divWidth))
	titleBlock := lipgloss.JoinVertical(lipgloss.Center, title, divider)

	codeStyle := lipgloss.NewStyle().Width(6) // width is 6 to be 1 larger than max code + Angstrom "A"
	descStyle := lipgloss.NewStyle()
	checkStyle := styles.MenuSelected
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
	list = lipgloss.NewStyle().PaddingLeft(2).Render(list)

	block := lipgloss.JoinVertical(lipgloss.Left,
		titleBlock, "", list,
	)

	// we add +1 to the height to account for the blank spacer line after the title block in joinVertical
	rowStart := lipgloss.Height(titleBlock) + 1
	return block, rowStart
}
