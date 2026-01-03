package flares

// clampViewport keeps cursor/offset within bounds for a viewport of given length and height.
func clampViewport(cursor, offset, length, height int) (int, int) {
	if height <= 0 || length <= 0 {
		return 0, 0
	}
	if cursor < 0 {
		cursor = 0
	}
	if cursor >= length {
		cursor = length - 1
	}
	if cursor < offset {
		offset = cursor
	}
	if cursor >= offset+height {
		// offset and height make up the rows from the top of the block to the bottom of visible ooptions.
		// Thus, offset + height give the row number with respect to the top of the block in question,
		// or the cursor. We add a +1 to shift the window just enough so the cursor lands on the last
		// visible row instead of the one past it. Else, for optiosn 0-9, we would be on 10, a non visible row,
		// at the end, before moving the view downwards.
		offset = cursor - height + 1
	}
	// length is total number of items in the list we are viewing. Height is number of visible rows in the window.
	// If length - height is negative, then the first visible row will be too far down and the window will have
	// empty rows at the end.
	maxOffset := max(length-height, 0)
	if offset > maxOffset {
		offset = maxOffset
	}
	if offset < 0 {
		offset = 0
	}
	return cursor, offset
}

func clampHeight(length, minH, maxH int) int {
	if length < minH {
		return max(minH, length)
	}
	if length > maxH {
		return maxH
	}
	return length
}
