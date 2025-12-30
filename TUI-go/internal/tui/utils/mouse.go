// Package utils is the hub for logic that is used in a variety of features to prevent duplication
// and redundancy piling up in the codebase
package utils

import "github.com/charmbracelet/lipgloss"

type MouseMapFunc func(relX, relY int) (int, int, bool)

type MouseHitSpec struct {
	X        int          // mouse x
	Y        int          // mouse y
	Width    int          // width of terminal
	Header   string       // rendered header for spacing
	Block    string       // rendered center block for mouse detection
	TopPad   int          // how much padding for the hitbox at the top
	NudgeX   int          // a small horizontal offset applied before centering on the hitbox
	CheckX   bool         // true: center block + reject hits outside horizontal bounds, false: only use y
	RowStart int          // the idex for row starting options
	RowCount int          // index for ending options
	Mapper   MouseMapFunc // MouseMapFunc maps relative coordinates inside a block to a result.
}

// MouseHit performs a centered block hit test and optional row mapping.
func MouseHit(spec MouseHitSpec) (int, int, bool) {
	// we return 2 ints and a bool. The first int is the column index, the second int is
	// the row index, and the bool is to check if we will use mouse detection at all. If we
	// return false, we dont use the first two values, so we just set them to zero.

	// reject absurd initial conditions and return the default index + no mouse hit
	if spec.X < 0 || spec.Y < 0 || spec.Block == "" {
		return 0, 0, false
	}

	// we now calculate where the block starts and reject hits outside its vertical span
	headerHeight := lipgloss.Height(spec.Header) + spec.TopPad // space until we reach block first line
	blockHeight := lipgloss.Height(spec.Block)
	if spec.Y < headerHeight || spec.Y >= headerHeight+blockHeight {
		return 0, 0, false
	}

	relY := spec.Y - headerHeight
	relX := spec.X
	// we do the same process as with y, just using offset from centering isntead of height
	if spec.CheckX {
		blockWidth := lipgloss.Width(spec.Block)
		offset := 0
		if spec.Width > blockWidth {
			// we find the offset used to center the block
			offset = (spec.Width - blockWidth) / 2
		}
		offset += spec.NudgeX   // we add an additional nudge on top of this
		offset = max(offset, 0) // clamp in case we make a block too big or bug

		relX = spec.X - offset
		if relX < 0 || relX >= blockWidth { // horizontal boundary check
			return 0, 0, false
		}
	}

	if spec.Mapper != nil {
		return spec.Mapper(relX, relY)
	}

	if spec.RowCount <= 0 {
		return 0, 0, false
	}
	if relY < spec.RowStart || relY >= spec.RowStart+spec.RowCount { // vertical boundary check
		return 0, 0, false
	}
	return 0, relY - spec.RowStart, true
	// we return the coordinates relative to the top of the given block, not necessarily the same
	// thing as the relative option coordinates (especially if we have a title or things above option select)
}
