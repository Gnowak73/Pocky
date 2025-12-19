// Package flares encapsulated all flare-related things that do not mutate the state of the TUI model. This includes
// python querying, choosing filtering comparators, managing the cache state, etc.
package flares

import (
	"fmt"

	"github.com/charmbracelet/lipgloss"
	lgtbl "github.com/charmbracelet/lipgloss/table"
	"github.com/pocky/tui-go/internal/tui/styles"
)

type Entry struct {
	Desc  string
	Class string
	Start string
	End   string
	Coord string
	Full  string
	Wave  string
}

type SpinnerState struct {
	Frames []string
	Index  int
}

type SelectorState struct {
	List     []Entry // slice of entries
	Header   string
	Selected map[int]bool
	Cursor   int // just an int representing which row we are on
	Offset   int // index of first visible item in flare list
	Loading  bool
	Spinner  SpinnerState
}

func NewSelectorState() SelectorState {
	return SelectorState{
		Selected: make(map[int]bool),
		Spinner: SpinnerState{
			Frames: []string{"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"},
		},
	}
}

func (s SelectorState) viewHeight() int {
	// defensive code
	if len(s.List) == 0 {
		return 0
	}
	// clamp between 7 and 12 rows so viewport doesnt grow or shrink windly while scrolling
	return max(7, min(12, len(s.List)))
}

func (s SelectorState) Render(width int) string {
	// this function is called every time we render the table in the View()
	if s.Loading {
		// spinner frames is only checked for the animation. However, if there is an empty string
		// we may still move foreward and get this function called where the index is just zero (since
		// empty spinner frames skip moving the index forward and it's initialized at 0). Since
		// indexing an empty string returns a panic error, we add this fallback
		spin := ""
		if len(s.Spinner.Frames) > 0 {
			spin = s.Spinner.Frames[s.Spinner.Index%len(s.Spinner.Frames)]
		}

		msg := styles.LightGray.Render(fmt.Sprintf("Loading flares %s", spin))

		// we now must join our rendered strings together and join them to be outputted later to the TUI

		// defensive code
		block := lipgloss.JoinVertical(lipgloss.Center, "", msg)
		if width <= 0 {
			return "\n" + block
		}

		// lipgloss.Place creates a rectangular view and pads the inside strings, we want a centered output
		// with height equal to the block we are rendering
		return "\n" + lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	}

	// render the top title header with lipgloss Render which returns useful strings to print
	// after wrapping in ASCII escapte codes etc.
	title := styles.SummaryHeader.Bold(false).Render("Choose Flares to Catalogue (Scroll)")
	height := s.viewHeight()

	tableStr := renderSelectFlaresTable(s, width, height)

	if width > 0 {
		title = lipgloss.Place(width, lipgloss.Height(title), lipgloss.Center, lipgloss.Top, title)
	} else {
		title = lipgloss.Place(lipgloss.Width(tableStr), lipgloss.Height(title), lipgloss.Center, lipgloss.Top, title)
	}
	body := lipgloss.JoinVertical(lipgloss.Left, title, "", tableStr)
	help := styles.LightGray.Render("↑/↓ move • space toggle • enter save • esc cancel")

	// defensive code so lipgloss.Placed doesnt divide up a space of zero width
	if width <= 0 {
		return "\n\n" + body + "\n\n" + help
	}

	placed := lipgloss.Place(width, lipgloss.Height(body), lipgloss.Center, lipgloss.Top, body)
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	return "\n\n" + placed + "\n\n" + helpLine
}

// renderSelectFlaresTable builds the flare selection table with distinct columns and a selectable SEL column.
func renderSelectFlaresTable(state SelectorState, width int, height int) string {
	// The offset tells us the first index in the table which should be visible. As we haven't moved
	// our cursor yet, we want this to start at zero. This function will be called whenever we are Rendering the table.
	// The height and width to be used will come from the SelectorState, or how many columns we space and
	// how many lines fit in the table window at one time (between 7 and 12)

	// Hence, we first "start" at the max of the offset and 0 (choosing between 0 or where the cursor is). However
	// start must also be <= length(state.List) - height, or else at the bottom of the table we will go past the
	// last row in terms of rendered space. We want the last possible start to be the height above the bottom to
	// end scrolling on the last few.
	start := max(state.Offset, 0)
	if max := max(len(state.List)-height, 0); start > max {
		start = max
	}
	// we bound the bottom by either the entire length of the table or "height" number of rows after the start,
	// esentially making the window "height" rows tall which we view at all times. We need a min for the case we have
	// less than "height" number of rows to supply, then we end is the bottom of the whole list.
	end := min(len(state.List), start+height)

	// glamour
	base := lipgloss.NewStyle().Padding(0, 1)
	headerStyle := base.Inherit(styles.VeryLightGray).Bold(true)
	cursorStyle := base.Inherit(styles.MenuSelected).Background(lipgloss.Color("#2A262A"))
	selectColStyle := base.Foreground(lipgloss.Color("#C7CDD6"))
	classEvenStyle := base.Inherit(styles.Gray)
	classOddStyle := base.Inherit(styles.VeryLightGray)
	coordEvenStyle := base.Foreground(lipgloss.Color("#B8C3D9"))
	coordOddStyle := base.Foreground(lipgloss.Color("#A0A9BE"))
	startendEvenStyle := base.Inherit(styles.LightGray)
	startendOddStyle := base.Inherit(styles.Gray)
	evenStyle := base.Inherit(styles.Gray)
	oddStyle := base.Inherit(styles.VeryLightGray)
	selMark := styles.MenuSelected

	rows := make([][]string, 0, end-start)
	for i := start; i < end; i++ {
		entry := state.List[i]
		sel := "[ ]"
		if state.Selected[i] {
			sel = selMark.Render("[x]")
		}
		rows = append(rows, []string{
			sel,
			entry.Class,
			entry.Start,
			entry.End,
			entry.Coord,
		})
	}

	// we now crate the glorious lipgloss table
	t := lgtbl.New().
		Border(lipgloss.NormalBorder()).
		BorderStyle(styles.FaintGray).
		Headers("SEL", "CLASS", "START", "END", "COORDINATES").
		Rows(rows...).
		StyleFunc(func(row, col int) lipgloss.Style {
			if row == lgtbl.HeaderRow {
				return headerStyle
			}
			abs := start + row
			if abs == state.Cursor {
				return cursorStyle
			}
			if col == 0 {
				return selectColStyle
			}
			evenRow := abs%2 == 0
			switch col {
			case 1:
				if evenRow {
					return classEvenStyle
				}
				return classOddStyle
			case 2, 3:
				if evenRow {
					return startendEvenStyle
				}
				return startendOddStyle
			case 4:
				if evenRow {
					return coordEvenStyle
				}
				return coordOddStyle
			}
			if abs%2 == 0 {
				return evenStyle
			}
			return oddStyle
		})

	tableStr := t.String()
	if width > 0 {
		tableStr = lipgloss.Place(width, lipgloss.Height(tableStr), lipgloss.Center, lipgloss.Top, tableStr)
	}
	return tableStr
}

// EnsureVisible adjusts the offset so the cursor row remains within the viewport.
func (s *SelectorState) EnsureVisible() {
	h := s.viewHeight()
	if h <= 0 {
		s.Offset = 0
		return
	}
	if s.Cursor < 0 {
		s.Cursor = 0
	}
	if s.Cursor >= len(s.List) {
		s.Cursor = len(s.List) - 1
	}
	if s.Cursor < s.Offset {
		s.Offset = s.Cursor
	}
	if s.Cursor >= s.Offset+h {
		s.Offset = s.Cursor - h + 1
	}
	maxOffset := max(len(s.List)-h, 0)
	if s.Offset > maxOffset {
		s.Offset = maxOffset
	}
	if s.Offset < 0 {
		s.Offset = 0
	}
}
