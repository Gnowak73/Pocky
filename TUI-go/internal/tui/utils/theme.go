package utils

import (
	"github.com/charmbracelet/lipgloss"
	"github.com/lucasb-eyer/go-colorful"
)

type number interface {
	~int | ~float64
}

func Clamp[T number](x, min, max T) T {
	if x < min {
		return min
	}
	if x > max {
		return max
	}
	return x
}

func BlendHex(a, b string, t float64) string {
	c1, err1 := colorful.Hex(a)
	c2, err2 := colorful.Hex(b)
	if err1 != nil {
		c1 = colorful.Color{}
	}
	if err2 != nil {
		c2 = colorful.Color{}
	}
	t = Clamp(t, 0, 1)
	return c1.BlendHcl(c2, t).Hex()
}

func BlendStops(stops []colorful.Color, t float64) colorful.Color {
	if len(stops) == 0 {
		return colorful.Color{}
	}
	if len(stops) == 1 {
		return stops[0]
	}
	t = Clamp(t, 0, 1)
	span := float64(len(stops) - 1)
	pos := t * span
	idx := int(pos)
	if idx >= len(stops)-1 {
		return stops[len(stops)-1]
	}
	frac := pos - float64(idx)
	return stops[idx].BlendHcl(stops[idx+1], frac)
}

func RenderGradientText(text, startHex, endHex string, base lipgloss.Style) string {
	runes := []rune(text)
	if len(runes) == 0 {
		return ""
	}

	start, err := colorful.Hex(startHex)
	if err != nil {
		start = colorful.Color{}
	}
	end, err := colorful.Hex(endHex)
	if err != nil {
		end = colorful.Color{}
	}

	var parts []string
	steps := len(runes)
	for i, r := range runes {
		t := 0.0
		if steps > 1 {
			t = float64(i) / float64(steps-1)
		}
		col := start.BlendHcl(end, t)
		s := base
		parts = append(parts, s.Foreground(lipgloss.Color(col.Hex())).Render(string(r)))
	}
	return lipgloss.JoinHorizontal(lipgloss.Left, parts...)
}
