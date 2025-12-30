package flares

import (
	"github.com/charmbracelet/lipgloss"
)

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

	colStartX := []int{0, wCol0 + pad, wCol0 + pad + wCol1 + pad}
	colWidths := []int{wCol0, wCol1, wCol2}
	colIdx = -1 // sentinel value

	for i := range 3 {
		if relX >= colStartX[i] && relX < colStartX[i]+colWidths[i] {
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

	rowIdx = optY - 2 // subtract lines for per-column subtitle + divider

	var start, window, maxRows int
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
			start = max(state.MagIdx-window/2, 0)
			start = min(start, maxRows-window)
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
