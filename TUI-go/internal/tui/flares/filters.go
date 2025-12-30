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
	Display string // what is displayed on the screen
	Value   string // the actual mathematical value
}

type FilterState struct {
	Comparators  []Comparator
	CompDisplays []string // precomputed display strings from Comparators for rendering
	ClassLetters []string // GOES class letters list
	Magnitudes   []string // list of numeric magnitudes 0.0-9.9
	Focus        int      // the active column: 0=comp, 1=letter, 2=mag
	CompIdx      int      // selected comparator index
	LetterIdx    int      // selected class index
	MagIdx       int      // selected magnitude index
	FocusFrame   int      // animation frame when focus last changed
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
	// we need to read the current Config and return the matching indices for comparator,
	// class, letter, and magnitude so the UI can highlight the correct selection.
	// We will input the comps (list of comparator options) and the goes letter list. The output
	// will be the selected indexes for comparator, letter, and magnitude.

	// if no config fall back to 0's
	compIdx := 0
	letterIdx := 0
	magIdx := 0

	currentComp := strings.TrimSpace(cfg.Comparator)
	currentClass := strings.TrimSpace(cfg.FlareClass) // config combines magnitude and class

	for i, c := range comps {
		if c.Value == currentComp {
			compIdx = i
			break
		}
	}

	// since its stored in form [Letter][Magnitude] like A3.7, we want the currentClass to have
	// length 4. As long as its length is >= 1, we can first get the letter.
	if len(currentClass) >= 1 {
		letter := string(currentClass[0]) // index gives byte, not rune or string
		for i, l := range letters {
			if l == letter {
				letterIdx = i
				break
			}
		}
		// once we have the letter, we ignore it and look for the last 3 spaces
		mag := currentClass[1:]
		if len(mag) > 2 {
			// string[idx] gives a byte value in decimal. If we subtract '0', which acts as
			// some reference byte that is incremented to get all following numeric chars,
			// then we get the integer form of string[idx].
			magIdx = int(mag[0]-'0')*10 + int(mag[2]-'0') // turn uint8 into int
		}
	}

	return compIdx, letterIdx, magIdx
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
