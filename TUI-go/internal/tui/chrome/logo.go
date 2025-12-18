package chrome

import (
	"errors"
	"math"
	"os"
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/lucasb-eyer/go-colorful"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/styles"
	"github.com/pocky/tui-go/internal/tui/theme"
)

type LogoState struct {
	Lines   []string
	Colored []string
	BlockW  int
}

func LoadLogo() ([]string, error) {
	path := config.ParentDirFile("logo.txt")
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, errors.New("could not find logo.txt in parent /Pocky directory")
	}

	content := strings.TrimRight(string(data), "\r\n")
	if content == "" {
		return nil, errors.New("logo.txt is empty")
	}
	return strings.Split(content, "\n"), nil
}

func NewLogoState(logoLines []string, frame int) LogoState {
	blockW := 0
	for _, l := range logoLines {
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

	for i, line := range lines {
		lineStyled := gradient[i].Render(line)
		lineW := lipgloss.Width(lineStyled)
		extra := max(blockW-lineW, 0)
		basePad := extra / 2
		shift := int(math.Round(math.Sin(float64(frame)*speed+float64(i)*phase+offset) * amp))
		left := theme.Clamp(basePad+shift, 0, extra)
		right := extra - left
		colored[i] = strings.Repeat(" ", left) + lineStyled + strings.Repeat(" ", right)
	}
	return colored
}

func buildGradient(count int) []lipgloss.Style {
	if count < 1 {
		count = 1
	}

	stops := make([]colorful.Color, len(styles.GradientStops))
	for i := range styles.GradientStops {
		hex := styles.GradientStops[len(styles.GradientStops)-1-i]
		c, err := colorful.Hex(hex)
		if err != nil {
			c = colorful.Color{}
		}
		stops[i] = c
	}

	stylesOut := make([]lipgloss.Style, count)
	for i := range count {
		t := 0.0
		if count > 1 {
			t = float64(i) / float64(count-1)
		}
		color := theme.BlendStops(stops, t)
		stylesOut[i] = lipgloss.NewStyle().Foreground(lipgloss.Color(color.Hex()))
	}
	return stylesOut
}
