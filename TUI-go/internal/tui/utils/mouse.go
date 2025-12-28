package utils

import "github.com/charmbracelet/lipgloss"

// MouseMapFunc maps relative coordinates inside a block to a result.
type MouseMapFunc func(relX, relY int) (int, int, bool)

// MouseHitSpec describes the layout needed for a generic mouse hit test.
type MouseHitSpec struct {
	X        int
	Y        int
	Width    int
	Header   string
	Block    string
	TopPad   int
	NudgeX   int
	CheckX   bool
	RowStart int
	RowCount int
	Mapper   MouseMapFunc
}

// MouseHit performs a centered block hit test and optional row mapping.
func MouseHit(spec MouseHitSpec) (int, int, bool) {
	if spec.X < 0 || spec.Y < 0 || spec.Block == "" {
		return 0, 0, false
	}

	headerHeight := lipgloss.Height(spec.Header) + spec.TopPad
	blockHeight := lipgloss.Height(spec.Block)
	if spec.Y < headerHeight || spec.Y >= headerHeight+blockHeight {
		return 0, 0, false
	}

	relY := spec.Y - headerHeight
	relX := spec.X
	if spec.CheckX {
		blockWidth := lipgloss.Width(spec.Block)
		offset := 0
		if spec.Width > blockWidth {
			offset = (spec.Width - blockWidth) / 2
		}
		offset += spec.NudgeX
		if offset < 0 {
			offset = 0
		}
		relX = spec.X - offset
		if relX < 0 || relX >= blockWidth {
			return 0, 0, false
		}
	}

	if spec.Mapper != nil {
		return spec.Mapper(relX, relY)
	}

	if spec.RowCount <= 0 {
		return 0, 0, false
	}
	if relY < spec.RowStart || relY >= spec.RowStart+spec.RowCount {
		return 0, 0, false
	}
	return 0, relY - spec.RowStart, true
}
