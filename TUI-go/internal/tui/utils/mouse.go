package utils

// CenterOffset returns the left padding needed to center a block within width.
// nudge is an extra adjustment applied after centering.
func CenterOffset(width int, blockWidth int, nudge int) int {
	offset := 0
	if width > blockWidth {
		offset = (width - blockWidth) / 2
	}
	offset += nudge
	if offset < 0 {
		return 0
	}
	return offset
}

// HitList returns the row index for a vertical list given a top offset and row start.
// top is the absolute top of the block; start is the first row within the block.
func HitList(y int, top int, start int, count int) (int, bool) {
	first := top + start
	last := first + count
	if y < first || y >= last {
		return 0, false
	}
	return y - first, true
}

// HitBlockX returns the relative X within a centered block.
func HitBlockX(x int, width int, blockWidth int, nudge int) (int, bool) {
	offset := CenterOffset(width, blockWidth, nudge)
	relX := x - offset
	if relX < 0 || relX >= blockWidth {
		return 0, false
	}
	return relX, true
}
