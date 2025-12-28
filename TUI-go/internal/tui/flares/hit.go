package flares

import (
	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/internal/tui/utils"
)

// HitFilterColumns maps mouse coordinates to a filter column/row based on the rendered filter block.
func HitFilterColumns(state FilterState, frame int, width int, x, y int) (colIdx int, rowIdx int, ok bool) {
	block, _, blockWidth, titleHeight := RenderFilterBlock(state, frame)
	cols := RenderFilterColumns(state, frame)
	if len(cols) != 3 {
		return 0, 0, false
	}

	nudge := 0
	if width > blockWidth {
		if (width-blockWidth)/2 > 2 {
			nudge = -2
		}
	}

	colIdx, rowIdx, ok = utils.MouseHit(utils.MouseHitSpec{
		X:      x,
		Y:      y,
		Width:  width,
		Header: "",
		Block:  block,
		TopPad: 0,
		NudgeX: nudge,
		CheckX: true,
		Mapper: func(relX, relY int) (int, int, bool) {
			return HitFilterColumnsRel(state, frame, titleHeight, cols, relX, relY)
		},
	})
	return colIdx, rowIdx, ok
}

// HitFilterColumnsRel maps relative coordinates inside the filter block to a column/row.
func HitFilterColumnsRel(state FilterState, frame int, titleHeight int, cols []string, relX int, relY int) (colIdx int, rowIdx int, ok bool) {
	headerHit := relY < titleHeight+2 && relY > titleHeight-2
	optY := relY - titleHeight

	col0 := cols[0]
	col1 := cols[1]
	col2 := cols[2]
	pad := 2
	colStartX := []int{0, lipgloss.Width(col0) + pad, lipgloss.Width(col0) + pad + lipgloss.Width(col1) + pad}
	colWidths := []int{lipgloss.Width(col0), lipgloss.Width(col1), lipgloss.Width(col2)}
	colIdx = -1
	for i := 0; i < 3; i++ {
		if relX >= colStartX[i] && relX < colStartX[i]+colWidths[i] {
			colIdx = i
			break
		}
	}
	if colIdx == -1 {
		return 0, 0, false
	}

	if headerHit {
		return colIdx, 0, true
	}
	if optY < 2 {
		return 0, 0, false
	}
	rowIdx = optY - 2

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
