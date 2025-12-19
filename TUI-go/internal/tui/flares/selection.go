package flares

import (
	"fmt"

	"github.com/charmbracelet/bubbles/table"
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
	Table    table.Model
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

func (s SelectorState) styledRows() []table.Row {
	// we arent modifying the state, all we do is return a table with selected column

	// defensive code
	if len(s.List) == 0 {
		return nil
	}

	// take a list of flare entries and convert them into bubbletea table row,
	// which is read as just a slice of strings
	rows := make([]table.Row, 0, len(s.List))
	for i, entry := range s.List {
		check := "[ ]"
		if s.Selected[i] {
			check = "[x]"
		}
		rows = append(rows, table.Row{check, entry.Class, entry.Start, entry.End, entry.Coord})
	}
	return rows
}

func (s *SelectorState) RebuildTable() {
	// we are fully reconstructing the table.Model from the current selector state. The selector
	// keeps a table.Model so it can display the catalogue of flares without reinventing layout/scrolling
	// constructs. RebuildTable creates that model whenever the SelectorState.List, Cursor, or the selected
	// rows change. Hence why we call it a "rebuild."
	// pass the selector state into the function, then we modify

	wSel, wClass, wstart, wend, wCoord := flareTableWidths(*s)
	columns := []table.Column{
		{Title: "SEL", Width: wSel},
		{Title: "CLASS", Width: wClass},
		{Title: "START", Width: wstart},
		{Title: "END", Width: wend},
		{Title: "COORDINATES", Width: wCoord},
	}

	rows := s.styledRows()
	height := s.viewHeight()

	t := table.New(
		table.WithColumns(columns),
		table.WithRows(rows),
		table.WithHeight(height),
		table.WithFocused(true),
	)
	stylesTbl := table.DefaultStyles()

	stylesTbl.Header = stylesTbl.Header.
		Border(lipgloss.NormalBorder()).
		Inherit(styles.GrayBorder).
		BorderBottom(true).
		Inherit(styles.VeryLightGray).
		Bold(true).
		PaddingLeft(1).
		PaddingRight(1)

	stylesTbl.Selected = stylesTbl.Selected.
		Inherit(styles.Gray).
		Background(lipgloss.Color("")).
		Bold(false).
		PaddingLeft(1).
		PaddingRight(1)

	stylesTbl.Cell = stylesTbl.Cell.
		Align(lipgloss.Left).
		Inherit(styles.Gray).
		PaddingLeft(1).
		PaddingRight(1)

	t.SetStyles(stylesTbl)
	t.SetCursor(s.Cursor)
	s.Table = t
}

func (s *SelectorState) UpdateTableRows() {
	if len(s.List) == 0 || s.Table.Columns() == nil {
		return
	}

	// to update the rows, call back through to see which are selected and draw that
	// onto the TUI, then set that to the current rows of the table. Same with cursor
	rows := s.styledRows()
	s.Table.SetRows(rows)
	s.Table.SetCursor(s.Cursor)
}

func flareTableWidths(s SelectorState) (int, int, int, int, int) {
	wSel := lipgloss.Width("SEL")
	if wSel < lipgloss.Width("[x]") {
		wSel = lipgloss.Width("[x]")
	}
	wClass := lipgloss.Width("Class")
	wstart := lipgloss.Width("start")
	wend := lipgloss.Width("end")
	wCoord := lipgloss.Width("Coordinates")
	for _, e := range s.List {
		if w := lipgloss.Width(e.Class); w > wClass {
			wClass = w
		}
		if w := lipgloss.Width(e.Start); w > wstart {
			wstart = w
		}
		if w := lipgloss.Width(e.End); w > wend {
			wend = w
		}
		if w := lipgloss.Width(e.Coord); w > wCoord {
			wCoord = w
		}
	}
	pad := 2
	return wSel + pad, wClass + pad, wstart + pad, wend + pad, wCoord + pad
}

func (s SelectorState) Render(width int) string {
	title := styles.SummaryHeader.Copy().Bold(false).Render("Choose Flares to Catalogue (Scroll)")

	if s.Loading {
		spin := ""
		if len(s.Spinner.Frames) > 0 {
			spin = s.Spinner.Frames[s.Spinner.Index]
		}
		msg := styles.LightGray.Render(fmt.Sprintf("Loading flares %s", spin))
		block := lipgloss.JoinVertical(lipgloss.Center, "", msg)
		if width <= 0 {
			return "\n" + block
		}
		return "\n" + lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	}

	if len(s.List) == 0 {
		msg := styles.LightGray.Render("No flares found.")
		block := lipgloss.JoinVertical(lipgloss.Center, title, "", msg)
		if width <= 0 {
			return "\n\n" + block
		}
		return "\n\n" + lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	}

	height := s.viewHeight()
	if s.Cursor < 0 {
		s.Cursor = 0
	}
	if height == 0 {
		msg := styles.LightGray.Render("No flares found.")
		block := lipgloss.JoinVertical(lipgloss.Center, title, "", msg)
		if width <= 0 {
			return "\n\n" + block
		}
		return "\n\n" + lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	}
	tableStr := renderSelectFlaresTable(s, width, height)
	titleLine := title
	if width > 0 {
		titleLine = lipgloss.Place(width, lipgloss.Height(title), lipgloss.Center, lipgloss.Top, title)
	} else {
		titleLine = lipgloss.Place(lipgloss.Width(tableStr), lipgloss.Height(title), lipgloss.Center, lipgloss.Top, title)
	}
	body := lipgloss.JoinVertical(lipgloss.Left, titleLine, "", tableStr)
	help := styles.LightGray.Render("↑/↓ move • space toggle • enter save • esc cancel")

	if width <= 0 {
		return "\n\n" + body + "\n\n" + help
	}

	placed := lipgloss.Place(width, lipgloss.Height(body), lipgloss.Center, lipgloss.Top, body)
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	return "\n\n" + placed + "\n\n" + helpLine
}

// renderSelectFlaresTable builds the flare selection table with distinct columns and a selectable SEL column.
func renderSelectFlaresTable(state SelectorState, width int, height int) string {
	start := max(state.Offset, 0)
	if max := max(len(state.List)-height, 0); start > max {
		start = max
	}
	end := min(len(state.List), start+height)

	base := lipgloss.NewStyle().Padding(0, 1)
	headerStyle := base.Inherit(styles.VeryLightGray).Bold(true)
	cursorStyle := base.Foreground(lipgloss.Color("#F785D1")).Background(lipgloss.Color("#2A262A"))
	selectColStyle := base.Foreground(lipgloss.Color("#C7CDD6"))
	classEvenStyle := base.Inherit(styles.Gray)
	classOddStyle := base.Inherit(styles.VeryLightGray)
	coordEvenStyle := base.Foreground(lipgloss.Color("#B8C3D9"))
	coordOddStyle := base.Foreground(lipgloss.Color("#A0A9BE"))
	startendEvenStyle := base.Inherit(styles.LightGray)
	startendOddStyle := base.Inherit(styles.Gray)
	evenStyle := base.Inherit(styles.Gray)
	oddStyle := base.Inherit(styles.VeryLightGray)
	selMark := lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1"))

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
