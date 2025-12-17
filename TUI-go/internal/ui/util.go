package ui

import (
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/charmbracelet/lipgloss"
	"github.com/lucasb-eyer/go-colorful"
)

func parentDirFile(filename string) string {
	// we need to pull parent directory files or the
	// parent directory itself (use filename="") for env files, etc.
	// defines parent each time, if too much overhead consider global var
	var parent string

	if exe, err := os.Executable(); err == nil {
		exeDir := filepath.Dir(exe)
		parent = filepath.Dir(exeDir)
		return filepath.Join(parent, filename)
	}
	return ""
}

func isoToHuman(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return ""
	}
	s = strings.TrimSuffix(s, "Z")
	s = strings.ReplaceAll(s, "T", " ")
	if idx := strings.IndexRune(s, '.'); idx >= 0 {
		s = s[:idx]
	}
	return s
}

func centerContent(content string, width int) string {
	// aftering centering a viewport or "block" of info, the block
	// will be in the center of the screen but the text will still be
	// left oriented in the block, so we pad it accordingly

	if width <= 0 {
		return content
	}

	// may case uneven splitting for odd widths, keep note
	lines := strings.Split(content, "\n")
	for i, line := range lines {
		w := lipgloss.Width(line)
		if w < width {
			pad := (width - w) / 2
			lines[i] = strings.Repeat(" ", pad) + line
		}
	}
	return strings.Join(lines, "\n")
}

func renderGradientText(text, startHex, endHex string, base lipgloss.Style) string {
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
		// we copy the base style because if we pass through the original,
		// then when we apply the color on the return we are changing the base itself
		// making all text appear the gradient of the last run-through
		s := base
		parts = append(parts, s.Foreground(lipgloss.Color(col.Hex())).Render(string(r)))
	}
	return strings.Join(parts, "")
}

func unsetValue(val string) string {
	if strings.TrimSpace(val) == "" {
		return "<unset>"
	}
	return val
}

func clamp[T int | float64](x, min, max T) T {
	if x < min {
		return min
	}
	if x > max {
		return max
	}
	return x
}

func validDate(val string) bool {
	val = strings.TrimSpace(val)
	if val == "" {
		return false
	}
	if len(val) != len("2006-01-02") {
		return false
	}
	_, err := time.Parse("2006-01-02", val)
	return err == nil
}

func chronological(start, end string) bool {
	s, err1 := time.Parse("2006-01-02", start)
	e, err2 := time.Parse("2006-01-02", end)
	if err1 != nil || err2 != nil {
		return false
	}
	return !s.After(e)
}

func comparatorDisplayList(comp []comparator) []string {
	out := make([]string, len(comp))
	for i, c := range comp {
		out[i] = c.display
	}
	return out
}
