// Package chrome is for pure presentation of primitives and the logo. Rendering the menu, cache, etc.
// It also holds the logo state. No routing, jst taking in data and returning strings.
package chrome

import (
	"fmt"
	"math"
	"os"
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/lucasb-eyer/go-colorful"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/styles"
	"github.com/pocky/tui-go/internal/tui/utils"
)

type LogoState struct {
	Lines   []string // string linees for logo.txt
	Colored []string // colored lines
	BlockW  int      // column width to occupy
}

func LoadLogo() ([]string, error) {
	// we need to find the directory of the parent file and test if
	// the logo exists in /exeDir..

	path := config.ParentDirFile("logo.txt")

	// you cannot use go run . because this runs the exe from a temp
	// directory and not from the disk path

	// we read as bytes, but want the output as a string
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("could not find logo.txt in parent /Pocky directory")
	}

	// remove new line trailing characters
	content := strings.TrimRight(string(data), "\r\n")
	if content == "" {
		return nil, fmt.Errorf("logo.txt is empty")
	}
	return strings.Split(content, "\n"), nil
}

func NewLogoState(logoLines []string, frame int) LogoState {
	// we want the max visual line with of the logo to draw a border
	// and center it appropriately later on. This will be called in the
	// model initialization before we render the TUI
	blockW := 0
	for _, l := range logoLines {
		// the visual width of the logo as drawn by the TUI, measured
		// as column number (terminal draws based on grid)
		blockW = max(blockW, lipgloss.Width(l))
	}

	colored := ColorizeLogo(logoLines, blockW, frame)

	return LogoState{
		Lines:   logoLines,
		Colored: colored,
		BlockW:  blockW,
	}
}

func ColorizeLogo(lines []string, blockW int, frame int) []string {
	// color the logo with vertical gradient and add a gentle wave animation
	// using basic trig for glamour
	if len(lines) == 0 {
		return nil
	}

	gradient := buildGradient(len(lines))
	colored := make([]string, len(lines))

	const (
		amp    = 1.5
		speed  = 0.14
		phase  = 0.85
		offset = 0.0
	)

	// we use sine wave to model movement and pad to the left to move the logo lines.
	// We must also add/remove padding on the right to keep the overall space the same rectangle.
	for i, line := range lines {
		lineStyled := gradient[i].Render(line)
		lineW := lipgloss.Width(lineStyled)

		// while blockW >= lineW regularly, styled lines can change length,
		// so we put in max defensively. Use max and clamp in these cases.
		extra := max(blockW-lineW, 0)
		basePad := extra / 2

		shift := int(math.Round(math.Sin(float64(frame)*speed+float64(i)*phase+offset) * amp))
		left := utils.Clamp(basePad+shift, 0, extra)
		right := extra - left

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
	stops := make([]colorful.Color, len(styles.GradientStops))
	for i := range styles.GradientStops {
		hex := styles.GradientStops[len(styles.GradientStops)-1-i]
		c, err := colorful.Hex(hex)
		if err != nil {
			// upon error, return zero value of rgb by default
			c = colorful.Color{}
		}
		stops[i] = c
	}

	stylesOut := make([]lipgloss.Style, count)

	// When interpolating, the gradient is a function over [0,1], t=0 is
	// the first color and t=1 then next. To interpolate with "count" gradient
	// steps, we want an equal distribution so we split up [0,1] into equal parts
	// and sample those parts as t
	for i := range count {
		t := 0.0
		if count > 1 {
			t = float64(i) / float64(count-1)
		}
		color := blendStops(stops, t)
		stylesOut[i] = lipgloss.NewStyle().Foreground(lipgloss.Color(color.Hex()))
	}
	return stylesOut
}

func blendStops(stops []colorful.Color, t float64) colorful.Color {
	if len(stops) == 0 {
		return colorful.Color{}
	}
	if len(stops) == 1 {
		return stops[0]
	}
	t = utils.Clamp(t, 0, 1)
	span := float64(len(stops) - 1)
	pos := t * span
	idx := int(pos)
	if idx >= len(stops)-1 {
		return stops[len(stops)-1]
	}
	frac := pos - float64(idx)
	return stops[idx].BlendHcl(stops[idx+1], frac)
}
