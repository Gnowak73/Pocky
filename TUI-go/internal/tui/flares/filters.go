package flares

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/styles"
	"github.com/pocky/tui-go/internal/tui/utils"
)

type Comparator struct {
	Display string
	Value   string
}

type FilterState struct {
	Comparators  []Comparator
	CompDisplays []string
	ClassLetters []string
	Magnitudes   []string
	Focus        int // 0=comp, 1=letter, 2=mag
	CompIdx      int
	LetterIdx    int
	MagIdx       int
	FocusFrame   int
}

func NewFilterState(cfg config.Config) FilterState {
	comps := DefaultComparator()
	letters := DefaultClassLetters()
	mags := DefaultMagnitudes()
	compIdx, letterIdx, magIdx := ParseFilterSelection(cfg, comps, letters)
	return FilterState{
		Comparators:  comps,
		CompDisplays: comparatorDisplayList(comps),
		ClassLetters: letters,
		Magnitudes:   mags,
		CompIdx:      compIdx,
		LetterIdx:    letterIdx,
		MagIdx:       magIdx,
	}
}

func DefaultComparator() []Comparator {
	return []Comparator{
		{">", ">"},
		{"≥", ">="},
		{"≡", "=="},
		{"≤", "<="},
		{"<", "<"},
		{"All", "All"},
	}
}

func DefaultClassLetters() []string {
	return []string{"A", "B", "C", "M", "X"}
}

func DefaultMagnitudes() []string {
	mags := make([]string, 0, 100)
	for i := range 10 {
		for t := range 10 {
			mags = append(mags, fmt.Sprintf("%d.%d", i, t))
		}
	}
	return mags
}

func ParseFilterSelection(cfg config.Config, comps []Comparator, letters []string) (int, int, int) {
	compIdx := 0
	letterIdx := 0
	magIdx := 0

	currentComp := strings.TrimSpace(cfg.Comparator)
	currentClass := strings.TrimSpace(cfg.FlareClass)

	for i, c := range comps {
		if c.Value == currentComp {
			compIdx = i
			break
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
		mag := currentClass[1:]
		if len(mag) > 2 {
			magIdx = int(mag[0]-'0')*10 + int(mag[2]-'0')
		}
	}

	return compIdx, letterIdx, magIdx
}

func ComparatorASCII(val string) string {
	val = strings.TrimSpace(val)
	switch val {
	case "≥":
		return ">="
	case "≤":
		return "<="
	case "All", "ALL":
		return "All"
	case "≡":
		return "=="
	default:
		return val
	}
}

func PrettyComparator(val string) string {
	val = strings.TrimSpace(val)
	if val == "" {
		return "<unset>"
	}
	switch val {
	case ">=":
		return "≥"
	case "<=":
		return "≤"
	case "==":
		return "≡"
	default:
		return val
	}
}

func RenderFilterColumns(state FilterState, frame int) []string {
	headerStyle := styles.LightGray
	itemStyle := styles.PinkOption
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
			start = max(selected-window/2, 0)
			start = min(start, len(opts)-window)
		}
		end := min(len(opts), start+window)

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
			headerAnimT := utils.Clamp(float64(max(frame-state.FocusFrame, 0))/8.0, 0.0, 1.0)
			headerText = utils.RenderGradientText(
				title,
				utils.BlendHex("#7D5FFF", "#FFB7D5", headerAnimT),
				utils.BlendHex("#8B5EDB", "#F785D1", headerAnimT),
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

	compCol := renderColumn("Comparator",
		state.CompDisplays,
		state.CompIdx,
		state.Focus == 0,
		len(state.CompDisplays))

	letCol := renderColumn("GOES Class",
		state.ClassLetters,
		state.LetterIdx,
		state.Focus == 1,
		len(state.ClassLetters))

	magCol := renderColumn("Magnitude (Scroll)",
		state.Magnitudes,
		state.MagIdx,
		state.Focus == 2,
		9)

	return []string{
		lipgloss.NewStyle().PaddingRight(2).Render(compCol),
		lipgloss.NewStyle().PaddingRight(2).Render(letCol),
		magCol,
	}
}

func RenderFilterEditor(state FilterState, frame int, width int) string {
	block, blockHeight, _, _ := RenderFilterBlock(state, frame)
	help := styles.LightGray.Render("←/→/tab switch • ↑/↓ select • enter save • esc cancel")

	if width <= 0 {
		return "\n\n" + block + "\n\n" + help
	}

	placed := lipgloss.Place(width, blockHeight, lipgloss.Center, lipgloss.Top, block)
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	return "\n\n" + placed + "\n\n" + helpLine
}

// RenderFilterBlock builds the title+columns layout and returns the block string plus its dimensions.
// It also returns the height of the title block (including the blank line before columns) to align hit testing.
func RenderFilterBlock(state FilterState, frame int) (string, int, int, int) {
	titleStyle := styles.SummaryHeader.Bold(false)
	cols := RenderFilterColumns(state, frame)
	columns := lipgloss.JoinHorizontal(lipgloss.Top, cols...)
	title := titleStyle.Render("Set Flare Filters")
	colWidth := lipgloss.Width(columns)
	if colWidth < lipgloss.Width(title) {
		colWidth = lipgloss.Width(title)
	}
	divWidth := max(colWidth, lipgloss.Width(title)+6)
	divider := lipgloss.NewStyle().Foreground(lipgloss.Color("#3A3A3A")).Render(strings.Repeat("─", divWidth))
	titleBlock := lipgloss.JoinVertical(lipgloss.Center, title, divider)
	titleBlock = lipgloss.PlaceHorizontal(colWidth, lipgloss.Center, titleBlock)

	block := lipgloss.JoinVertical(lipgloss.Left, titleBlock, "", columns)
	titleHeight := lipgloss.Height(titleBlock) + 1 // plus the blank line before columns
	return block, lipgloss.Height(block), lipgloss.Width(block), titleHeight
}

func comparatorDisplayList(comp []Comparator) []string {
	out := make([]string, len(comp))
	for i, c := range comp {
		out[i] = c.Display
	}
	return out
}
