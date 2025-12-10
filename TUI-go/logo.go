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
	// and a gentle wave animation using basic trig
	if len(lines) == 0 {
		return nil
	}

	gradient := buildGradient(len(lines))
	colored := make([]string, len(lines))

	const (
		amp    = 1.5  // characters
		speed  = 0.14 // radians per tick
		phase  = 0.85 // radians per line
		offset = 0.0  // baseline shift
	)

	// we want to use sine to model movement in each line given a small offset
	// to make it appear like a wave. We will shift all lines by some amount,
	// and center it.
	for i, line := range lines {
		lineStyled := gradient[i].Render(line)
		lineW := lipgloss.Width(lineStyled)

		// while blockW >= lineW regularly, styled lines can change length,
		// so we put in max defensively. Use max and clamp in these cases.
		extra := max(blockW-lineW, 0)
		basePad := extra / 2

		shift := int(math.Round(math.Sin(float64(frame)*speed+float64(i)*phase+offset) * amp))

		left := clamp(basePad+shift, 0, extra)
		right := extra - left

		// we add spaces to left to move the lines and to the right so that
		// the total length still stays the block width as a whole, making a rectangle
		colored[i] = strings.Repeat(" ", left) + lineStyled + strings.Repeat(" ", right)
	}
	return colored
}

func buildGradient(count int) []lipgloss.Style {
	// we want to ensure at least one style exists so the linear
	// interpolation doesn't return an error (say we have empty string logo)
	if count < 1 {
		count = 1
	}

	// Reverse stops so gradient runs bottom-to-top relative to the input list
	// This allows the lighter colors to appear on bottom and not appear muddy
	// at the top where the hue is darker. We want to hold info in a slice of
	// colors recorded with RGB (originally HEX) and then render them
	stops := make([]colorful.Color, len(gradientStops))
	for i := range gradientStops {
		hex := gradientStops[len(gradientStops)-1-i]
		c, err := colorful.Hex(hex)
		if err != nil {
			// if error, return zero value of rgb color by default
			c = colorful.Color{}
		}
		stops[i] = c
	}

	styles := make([]lipgloss.Style, count)
	for i := range count {
		// When interpolating, the gradient is a function over [0,1], t=0 is
		// the first color and t=1 then next. To interpolate with "count" gradient
		// steps, we want an equal distribution so we split up [0,1] into equal parts
		// and sample those parts as t
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
	// for security we clamp to prevent error on blending
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
	// we will clamp for safety in case of future calls from elsewhere considering
	// the small cost. If we have N stops, there are N-1 segments. Multiplying t,
	// a valud in [0,1], with N-1 maps t smoothly across the segments. The integer
	// part of the position tells us which segment we are in, or the index idx.
	// [idx, idx+1] is then the segment we interpolate between. The decimal, part
	// of pos, frac, tells us how far along a segment we are (or how much we blend)
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
