// Package termemu provides a small terminal emulator tailored for streaming output.
// It supports carriage return, line clear, cursor movement, wrapping, and resize reflow.
package termemu

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
)

type Segment struct {
	Text    string
	Replace bool
}

type Emulator struct {
	Width       int
	MaxLines    int
	MaxSegments int

	lines    [][]rune
	row      int
	col      int
	segments []Segment
	pending  string
}

func New(width int) *Emulator {
	return &Emulator{
		Width:       width,
		MaxLines:    400,
		MaxSegments: 2000,
	}
}

func (e *Emulator) Reset() {
	e.lines = nil
	e.row = 0
	e.col = 0
	e.segments = nil
	e.pending = ""
}

func (e *Emulator) AppendSegment(text string, replace bool) {
	e.segments = append(e.segments, Segment{Text: text, Replace: replace})
	if e.MaxSegments > 0 && len(e.segments) > e.MaxSegments {
		e.segments = e.segments[len(e.segments)-e.MaxSegments:]
		e.rebuild()
		return
	}
	e.applySegment(Segment{Text: text, Replace: replace})
	e.trimLines()
}

func (e *Emulator) Resize(width int) {
	if width <= 0 || width == e.Width {
		return
	}
	e.Width = width
	e.rebuild()
}

func (e *Emulator) Render() string {
	if len(e.lines) == 0 {
		return ""
	}
	out := make([]string, 0, len(e.lines))
	for _, line := range e.lines {
		out = append(out, trimRightSpaces(string(line)))
	}
	return strings.Join(out, "\n")
}

func (e *Emulator) rebuild() {
	e.lines = nil
	e.row = 0
	e.col = 0
	for _, seg := range e.segments {
		e.applySegment(seg)
	}
	e.trimLines()
}

func (e *Emulator) applySegment(seg Segment) {
	if seg.Replace {
		e.carriageReturn()
		e.clearLine(2)
	}
	e.writeString(seg.Text)
}

func (e *Emulator) writeString(s string) {
	if e.pending != "" {
		s = e.pending + s
		e.pending = ""
	}
	runes := []rune(s)
	for i := 0; i < len(runes); i++ {
		r := runes[i]
		switch r {
		case '\r':
			e.carriageReturn()
			continue
		case '\n':
			e.lineFeed()
			continue
		case '\x1b':
			next, ok := e.consumeEscape(runes, i)
			if !ok {
				e.pending = string(runes[i:])
				return
			}
			i = next
			continue
		}
		e.writeRune(r)
	}
}

func (e *Emulator) consumeEscape(runes []rune, i int) (int, bool) {
	if i+1 >= len(runes) || runes[i+1] != '[' {
		return i, true
	}
	j := i + 2
	for j < len(runes) {
		ch := runes[j]
		if (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') {
			params := string(runes[i+2 : j])
			e.handleCSI(params, ch)
			return j, true
		}
		j++
	}
	return i, false
}

func (e *Emulator) handleCSI(params string, final rune) {
	n := parseCSIParam(params, 1)
	switch final {
	case 'A': // cursor up
		e.row -= n
		if e.row < 0 {
			e.row = 0
		}
	case 'B': // cursor down
		e.row += n
		e.ensureLine()
	case 'C': // cursor right
		e.col += n
	case 'D': // cursor left
		e.col -= n
		if e.col < 0 {
			e.col = 0
		}
	case 'G': // cursor horizontal absolute
		e.col = max(n-1, 0)
	case 'K': // clear line
		e.clearLine(parseCSIParam(params, 0))
	case 'H', 'f': // cursor position
		row, col := parseCSIParams(params)
		if row > 0 {
			e.row = row - 1
		} else {
			e.row = 0
		}
		if col > 0 {
			e.col = col - 1
		} else {
			e.col = 0
		}
		e.ensureLine()
	case 'J': // clear screen
		e.clearScreen(parseCSIParam(params, 0))
	}
}

func parseCSIParam(s string, def int) int {
	if s == "" {
		return def
	}
	val := 0
	for _, r := range s {
		if r < '0' || r > '9' {
			break
		}
		val = val*10 + int(r-'0')
	}
	if val == 0 {
		return def
	}
	return val
}

func parseCSIParams(s string) (int, int) {
	if s == "" {
		return 0, 0
	}
	parts := strings.Split(s, ";")
	row := 0
	col := 0
	if len(parts) > 0 {
		row = parseCSIParam(parts[0], 0)
	}
	if len(parts) > 1 {
		col = parseCSIParam(parts[1], 0)
	}
	return row, col
}

func (e *Emulator) writeRune(r rune) {
	if e.Width > 0 {
		rw := runeWidth(r)
		if e.col+rw > e.Width && e.col > 0 {
			e.lineFeed()
		}
	}
	e.ensureLine()
	line := e.lines[e.row]
	for len(line) < e.col {
		line = append(line, ' ')
	}
	if e.col < len(line) {
		line[e.col] = r
	} else {
		line = append(line, r)
	}
	e.lines[e.row] = line
	e.col += runeWidth(r)
}

func (e *Emulator) ensureLine() {
	for len(e.lines) <= e.row {
		e.lines = append(e.lines, []rune{})
	}
}

func (e *Emulator) lineFeed() {
	e.row++
	e.col = 0
	e.ensureLine()
	if e.MaxLines > 0 && len(e.lines) > e.MaxLines {
		trim := len(e.lines) - e.MaxLines
		e.lines = e.lines[trim:]
		e.row -= trim
		if e.row < 0 {
			e.row = 0
		}
	}
}

func (e *Emulator) carriageReturn() {
	e.col = 0
}

func (e *Emulator) clearLine(mode int) {
	e.ensureLine()
	line := e.lines[e.row]
	switch mode {
	case 1:
		for i := 0; i < e.col && i < len(line); i++ {
			line[i] = ' '
		}
	case 2:
		line = nil
	default:
		if e.col < len(line) {
			line = line[:e.col]
		}
	}
	e.lines[e.row] = line
}

func (e *Emulator) clearScreen(mode int) {
	switch mode {
	case 1:
		for i := 0; i <= e.row && i < len(e.lines); i++ {
			e.lines[i] = nil
		}
	case 2:
		e.lines = nil
		e.row = 0
		e.col = 0
	default:
		if e.row < len(e.lines) {
			e.lines = e.lines[:e.row]
		}
	}
	e.ensureLine()
}
func (e *Emulator) trimLines() {
	if e.MaxLines > 0 && len(e.lines) > e.MaxLines {
		trim := len(e.lines) - e.MaxLines
		e.lines = e.lines[trim:]
		e.row -= trim
		if e.row < 0 {
			e.row = 0
		}
	}
}

func runeWidth(r rune) int {
	return lipgloss.Width(string(r))
}

func trimRightSpaces(s string) string {
	return strings.TrimRight(s, " ")
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
