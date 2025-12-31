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

func comparatorDisplayList(comp []Comparator) []string {
	out := make([]string, len(comp))
	for i, c := range comp {
		out[i] = c.Display
	}
	return out
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
	// given the state, we will return a slice of strings, one for each column selector
	headerStyle := styles.LightGray
	itemStyle := styles.PinkOption
	checkStyle := styles.MenuSelected

	// we will start with a plain box and inherit the new styles on top of this
	plainBox := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		Padding(0, 1)

	renderColumn := func(title string, opts []string, selected int, focused bool, window int) string {
		start := 0 // the first visible row index
		// width is for the selector box, NOT the window width

		// if we have more options than the window, we will try to center it and then clamp it to not
		// go before index 0. We then will clamp so it doesn't run past the end either.
		if len(opts) > window {
			start = max(selected-window/2, 0)
			start = min(start, len(opts)-window)
		}
		end := min(len(opts), start+window) // we choose the max number of rows that is allowed to show

		var rows []string
		for i := start; i < end; i++ {
			prefix := "[ ]"
			if i == selected {
				prefix = checkStyle.Render("[x]")
			}
			line := lipgloss.JoinHorizontal(
				lipgloss.Top,
				prefix, " ", itemStyle.Render(opts[i]),
			)
			rows = append(rows, line)
		}

		headerText := headerStyle.Foreground(lipgloss.Color("#3A3A3A")).Render(title)
		if focused {
			// for the animation, we measure how many frames since focus started, we will use max
			// to prevent negative values, and scale by /8 so the animation reaches 1 after 8 frames.
			// clamp will keep the 0-1 range for interpolation as we go from startHex to endHex
			headerAnimT := utils.Clamp(float64(max(frame-state.FocusFrame, 0))/8.0, 0.0, 1.0)
			headerText = utils.RenderGradientText(
				title,
				utils.BlendHex("#7D5FFF", "#FFB7D5", headerAnimT),
				utils.BlendHex("#8B5EDB", "#F785D1", headerAnimT),
				headerStyle.Bold(true),
			)
		}

		content := lipgloss.JoinVertical(
			lipgloss.Left,
			headerText, "", strings.Join(rows, "\n"),
		)
		if focused {
			return plainBox.BorderForeground(lipgloss.Color("#F785D1")).Render(content)
		}
		return plainBox.BorderForeground(lipgloss.Color("#2B2B2B")).Render(content)
	}

	// we build three columns side by side
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

	return []string{ // to add padding to already render string we make new style will padding to seaprate columns
		lipgloss.NewStyle().PaddingRight(2).Render(compCol),
		lipgloss.NewStyle().PaddingRight(2).Render(letCol),
		magCol,
	}
}

func RenderFilterBlock(state FilterState, frame int) (string, int, int, int) {
	// before putting everything together, we need to be able to return the dimensions of the
	// tui menu for mouse testing along with a title and the summary

	titleStyle := styles.SummaryHeader.Bold(false)
	cols := RenderFilterColumns(state, frame)
	columns := lipgloss.JoinHorizontal(lipgloss.Top, cols...)
	title := titleStyle.Render("Set Flare Filters")

	colWidth := lipgloss.Width(columns)
	colWidth = max(colWidth, lipgloss.Width(title))
	divWidth := max(colWidth, lipgloss.Width(title)+6) // width for horizontal divider

	divider := lipgloss.NewStyle().
		Foreground(lipgloss.Color("#3A3A3A")).Render(strings.Repeat("─", divWidth))

	titleBlock := lipgloss.JoinVertical(lipgloss.Center, title, divider)
	titleBlock = lipgloss.PlaceHorizontal(colWidth, lipgloss.Center, titleBlock)

	block := lipgloss.JoinVertical(lipgloss.Left, titleBlock, "", columns)
	titleHeight := lipgloss.Height(titleBlock) + 1 // plus the blank line before columns
	return block, lipgloss.Height(block), lipgloss.Width(block), titleHeight
}

func RenderFilterEditor(state FilterState, frame int, width int) string {
	block, blockHeight, _, _ := RenderFilterBlock(state, frame)
	help := styles.LightGray.Render("←/→/tab switch • ↑/↓ select • enter save • esc cancel")

	if width <= 0 {
		return "\n\n" + block + "\n\n" + help
	}

	placed := lipgloss.Place(
		width,
		blockHeight,
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
	return "\n\n" + placed + "\n\n" + helpLine
}

func HitFilterColumnsRel(state FilterState, frame int, titleHeight int, cols []string, relX int, relY int) (colIdx int, rowIdx int, ok bool) {
	// after mouseHit is called, we are able to get the absolute mouse coordinates and map these t
	// relative coordinates of the rendered block we are in terms of rows/columns. In the case of the filters, we
	// need more because we have 3 different submenus to select within. We take the relative coordinates from this
	// and figure out which filter column and which row is under the cursor to update.

	// headerHit is a boolean that says the mouse is within a small vertical band around the header.
	// We wont track rows for the header, but we don't want to always have to put the mouse over an option
	// to switch focus
	headerHit := relY < titleHeight+2 && relY > titleHeight-2

	// since we a header over the options, the coordinates relative to the top of the block from mouseHit
	// is NOT the same as the coordinates of the options. We must subtract the height of the title.
	optY := relY - titleHeight

	col0 := cols[0]
	col1 := cols[1]
	col2 := cols[2]
	pad := 2

	wCol0 := lipgloss.Width(col0)
	wCol1 := lipgloss.Width(col1)
	wCol2 := lipgloss.Width(col2)

	colStartX := []int{0, wCol0 + pad, wCol0 + pad + wCol1 + pad} // horizontal layout
	colWidths := []int{wCol0, wCol1, wCol2}
	colIdx = -1 // sentinel value

	for i := range 3 {
		if relX >= colStartX[i] && relX < colStartX[i]+colWidths[i] { // hit within column x boundaries
			colIdx = i
			break
		}
	}

	if colIdx == -1 {
		return 0, 0, false
	}

	if headerHit { // we return the index and just default row 0 for the header select
		return colIdx, 0, true
	}

	// subtract lines for per-column subtitle + divider. This is zero at the top option in a column
	// and negative for any rows before it up to the top of the block, so w.r.t. the column options
	rowIdx = optY - 2

	var start, window, maxRows int // window is number of visible rows, maxRows is total options
	switch colIdx {
	case 0:
		window = len(state.CompDisplays)
		start = 0
		maxRows = len(state.CompDisplays)
	case 1:
		window = len(state.ClassLetters)
		start = 0
		maxRows = len(state.ClassLetters)
	case 2:
		window = 9
		maxRows = len(state.Magnitudes)
		if maxRows < window {
			window = maxRows
		}
		if maxRows > window {
			// we start at the top half of the window, or we clamp to the half way point when scrolling down
			start = max(state.MagIdx-window/2, 0)
			start = min(start, maxRows-window) // maxRows-window is largest valid start allowing full window to fit
		}
	default:
		return 0, 0, false
	}

	if rowIdx < 0 || rowIdx >= window {
		return 0, 0, false
	}

	actualIdx := start + rowIdx // the index with respect to the column, not the block
	if actualIdx >= maxRows {
		return 0, 0, false
	}

	return colIdx, actualIdx, true
}
