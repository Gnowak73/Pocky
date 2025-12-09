package main

import (
	"errors"
	"math"
	"os"
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/lucasb-eyer/go-colorful"
)

func loadLogo() ([]string, error) {
	// we want to find the directory of the exe file to then see
	// if logo.txt exist in /exeDir..

	path := parentDirFile("logo.txt")

	// you CANNOT use "go run ." because this runs the exe
	// from a tmp directory and not from the disk path

	// we read as bytes, but we want to output the string
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, errors.New("could not find logo.txt in parent /Pocky directory")
	}

	// for cutset we dont want trailing chars
	content := strings.TrimRight(string(data), "\r\n")
	if content == "" {
		return nil, errors.New("logo.txt is empty")
	}
	return strings.Split(content, "\n"), nil
}

func colorizeLogo(lines []string, blockW int, frame int) []string {
	// we want to colorize the logo with vertical gradien  for glamour
	// and a gentle wave animation using basic trig.
	if len(lines) == 0 {
		return nil
	}

	if blockW <= 0 {
		for _, l := range lines {
			if w := lipgloss.Width(l); w > blockW {
				blockW = w
			}
		}
	}

	gradient := buildGradient(len(lines))
	colored := make([]string, len(lines))

	const (
		amp    = 1.5  // characters
		speed  = 0.14 // radians per tick
		phase  = 0.85 // radians per line
		offset = 0.0  // baseline shift
	)

	for i, line := range lines {
		lineStyled := gradient[i].Render(line)
		lineW := lipgloss.Width(lineStyled)
		extra := blockW - lineW
		if extra < 0 {
			extra = 0
		}

		basePad := extra / 2

		shift := int(math.Round(math.Sin(float64(frame)*speed+float64(i)*phase+offset) * amp))

		left := clampInt(basePad+shift, 0, extra)
		right := extra - left

		colored[i] = strings.Repeat(" ", left) + lineStyled + strings.Repeat(" ", right)
	}
	return colored
}

func buildGradient(count int) []lipgloss.Style {
	if count < 1 {
		count = 1
	}

	// Reverse stops so gradient runs bottom-to-top relative to the original list.
	stops := make([]colorful.Color, len(gradientStops))
	for i := range gradientStops {
		hex := gradientStops[len(gradientStops)-1-i]
		c, err := colorful.Hex(hex)
		if err != nil {
			c = colorful.Color{}
		}
		stops[i] = c
	}

	styles := make([]lipgloss.Style, count)
	for i := 0; i < count; i++ {
		t := 0.0
		if count > 1 {
			t = float64(i) / float64(count-1)
		}
		color := blendStops(stops, t)
		styles[i] = lipgloss.NewStyle().Foreground(lipgloss.Color(color.Hex()))
	}

	return styles
}

func blendHex(a, b string, t float64) string {
	c1, err1 := colorful.Hex(a)
	c2, err2 := colorful.Hex(b)
	if err1 != nil {
		c1 = colorful.Color{}
	}
	if err2 != nil {
		c2 = colorful.Color{}
	}
	t = clamp(t, 0, 1)
	return c1.BlendHcl(c2, t).Hex()
}

func blendStops(stops []colorful.Color, t float64) colorful.Color {
	if len(stops) == 0 {
		return colorful.Color{}
	}
	if len(stops) == 1 {
		return stops[0]
	}

	t = clamp(t, 0, 1)
	span := float64(len(stops) - 1)
	pos := t * span
	idx := int(math.Floor(pos))

	if idx >= len(stops)-1 {
		return stops[len(stops)-1]
	}

	next := idx + 1
	frac := pos - float64(idx)
	return stops[idx].BlendHcl(stops[next], frac)
}
