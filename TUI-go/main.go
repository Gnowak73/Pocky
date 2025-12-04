package main

import (
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/lucasb-eyer/go-colorful"
)

var gradientStops = []string{
	"#443066",
	"#FF8855",
	"#FF6B81",
	"#FF4FAD",
	"#D147FF",
	"#8B5EDB",
}

var (
	logoBoxStyle = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("#8B5EDB")).
			Padding(1, 2)

	statusBarStyle = lipgloss.NewStyle().
			Background(lipgloss.Color("#353533")).
			Foreground(lipgloss.Color("#E7E7E7"))

	statusKeyStyle = lipgloss.NewStyle().
			Inherit(statusBarStyle).
			Foreground(lipgloss.Color("#FFFDF5")).
			Background(lipgloss.Color("#FF5F87")).
			Padding(0, 1).
			MarginRight(1).
			Bold(true)

	statusTextStyle = lipgloss.NewStyle().
			Inherit(statusBarStyle)

	statusHintStyle = lipgloss.NewStyle().
			Inherit(statusBarStyle).
			Foreground(lipgloss.Color("#A550DF")).
			Padding(0, 1)

	statusArrowStyle = lipgloss.NewStyle().
				Inherit(statusBarStyle)

	versionStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#8B5EDB")).
			Bold(true)

	menuItemStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#EAEAFF"))

	menuSelectedStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#8B5EDB")).
				Bold(true)

	summaryLabelStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#FFB7D5")).
				Width(12).
				Align(lipgloss.Right)

	summaryValueStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#FFB7D5"))

	summaryHeaderStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#EAEAFF")).
				Bold(true).
				Padding(0, 1).
				Align(lipgloss.Center)

	summaryBodyStyle = lipgloss.NewStyle().
				Padding(0, 1).
				Align(lipgloss.Left)

	summaryBorderStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#3A3A3A"))
)

type model struct {
	logoLines []string
	colored   []string
	cfg       config
	blockW    int
	width     int
	height    int
	frame     int
	pause     int
	menuItems []string
	selected  int
	notice    string
}

type config struct {
	WAVE        string
	START       string
	END         string
	SOURCE      string
	FLARE_CLASS string
	COMPARATOR  string
	DL_EMAIL    string
}

type tickMsg struct{}

func main() {
	logo, err := loadLogo()
	if err != nil {
		fmt.Println("pocky logo:", err)
		os.Exit(1)
	}

	cfg := loadConfig()
	m := newModel(logo, cfg)
	if err := tea.NewProgram(m, tea.WithAltScreen()).Start(); err != nil {
		fmt.Println("tui error:", err)
		os.Exit(1)
	}
}

func tick() tea.Cmd {
	return tea.Tick(time.Millisecond*80, func(time.Time) tea.Msg { return tickMsg{} })
}

func newModel(logo []string, cfg config) model {
	blockW := 0
	for _, l := range logo {
		if w := lipgloss.Width(l); w > blockW {
			blockW = w
		}
	}

	colored := colorizeLogo(logo, blockW, 0)

	menu := []string{
		"Edit Wavelength",
		"Edit Date Range",
		"Edit Flare Class Filter",
		"Select Flares",
		"Cache Options",
		"Download FITS",
		"Quit",
	}

	return model{
		logoLines: logo,
		colored:   colored,
		cfg:       cfg,
		blockW:    blockW,
		menuItems: menu,
	}
}

func (m model) Init() tea.Cmd {
	return tick()
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
	case tickMsg:
		m.frame++
		m.colored = colorizeLogo(m.logoLines, m.blockW, m.frame)
		return m, tick()
	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c", "q", "esc":
			return m, tea.Quit
		case "up", "k":
			if m.selected > 0 {
				m.selected--
			}
		case "down", "j":
			if m.selected < len(m.menuItems)-1 {
				m.selected++
			}
		case "enter", " ":
			if m.selected >= 0 && m.selected < len(m.menuItems) {
				m.notice = fmt.Sprintf("Selected: %s (not implemented yet)", m.menuItems[m.selected])
			}
		}
	}
	return m, nil
}

func (m model) View() string {
	if len(m.colored) == 0 {
		return "logo missing\n"
	}

	content := strings.Join(m.colored, "\n")
	boxContent := logoBoxStyle.Render(content)

	w := m.width
	if w <= 0 {
		w = lipgloss.Width(boxContent)
	}
	box := lipgloss.Place(w, lipgloss.Height(boxContent), lipgloss.Center, lipgloss.Top, boxContent)

	boxWidth := lipgloss.Width(boxContent)
	versionText := versionStyle.Render("VERSION: 0.2")
	leftPad := 0
	if w > boxWidth {
		leftPad = (w - boxWidth) / 2
	}
	versionLine := strings.Repeat(" ", leftPad) + lipgloss.Place(boxWidth, 1, lipgloss.Right, lipgloss.Top, versionText)

	summary := renderSummary(m.cfg, w)
	menu := renderMenu(m, w)

	status := renderStatus(w, m.blockW, len(m.colored))
	if m.height > 0 {
		contentHeight := lipgloss.Height(box) + 1 + lipgloss.Height(summary) + lipgloss.Height(menu)
		gap := maxInt(m.height-contentHeight-lipgloss.Height(status), 0)
		return box + "\n" + versionLine + summary + menu + strings.Repeat("\n", gap) + status
	}

	return box + "\n" + versionLine + summary + menu + "\n" + status
}

func loadLogo() ([]string, error) {
	paths := []string{
		"logo.txt",
		filepath.Join("..", "logo.txt"),
	}

	if wd, err := os.Getwd(); err == nil {
		paths = append(paths,
			filepath.Join(wd, "logo.txt"),
			filepath.Join(wd, "..", "logo.txt"),
		)
	}

	if exe, err := os.Executable(); err == nil {
		exeDir := filepath.Dir(exe)
		paths = append(paths,
			filepath.Join(exeDir, "logo.txt"),
			filepath.Join(exeDir, "..", "logo.txt"),
		)
	}

	seen := make(map[string]struct{})
	for _, p := range paths {
		if _, ok := seen[p]; ok {
			continue
		}
		seen[p] = struct{}{}

		data, err := os.ReadFile(p)
		if err != nil || len(data) == 0 {
			continue
		}

		content := strings.TrimRight(string(data), "\r\n")
		if content == "" {
			continue
		}
		return strings.Split(content, "\n"), nil
	}

	return nil, errors.New("could not find logo.txt (looked in CWD, parent, and executable directory)")
}

func loadConfig() config {
	paths := []string{
		".vars.env",
		filepath.Join("..", ".vars.env"),
	}

	var cfg config
	for _, p := range paths {
		data, err := os.ReadFile(p)
		if err != nil {
			continue
		}
		lines := strings.Split(string(data), "\n")
		for _, line := range lines {
			line = strings.TrimSpace(line)
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			parts := strings.SplitN(line, "=", 2)
			if len(parts) != 2 {
				continue
			}
			key := parts[0]
			val := strings.Trim(parts[1], "\"")
			switch key {
			case "WAVE":
				cfg.WAVE = val
			case "START":
				cfg.START = val
			case "END":
				cfg.END = val
			case "SOURCE":
				cfg.SOURCE = val
			case "FLARE_CLASS":
				cfg.FLARE_CLASS = val
			case "COMPARATOR":
				cfg.COMPARATOR = val
			case "DL_EMAIL":
				cfg.DL_EMAIL = val
			}
		}
		break
	}
	return cfg
}

// colorizeLogo renders the logo lines with a vertical gradient and applies a gentle wave offset.
func colorizeLogo(lines []string, blockW int, frame int) []string {
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

func renderStatus(width int, logoWidth int, lines int) string {
	w := width
	if w <= 0 {
		w = 0
	}

	statusKey := statusKeyStyle.Render("POCKY")
	statusArrow := statusArrowStyle.
		Foreground(statusBarStyle.GetBackground()).
		Background(statusKeyStyle.GetBackground()).
		Render("")
	info := " Main Menu"
	infoBox := statusTextStyle.Render(info)
	available := maxInt(w-lipgloss.Width(statusKey)-lipgloss.Width(statusArrow)-lipgloss.Width(infoBox), 0)
	hints := statusHintStyle.Width(available).Align(lipgloss.Right).Render("q/esc to quit")

	bar := lipgloss.JoinHorizontal(
		lipgloss.Top,
		statusKey,
		statusArrow,
		infoBox,
		hints,
	)

	if w > 0 {
		return statusBarStyle.Width(w).Render(bar)
	}
	return statusBarStyle.Render(bar)
}

func renderMenu(m model, width int) string {
	var lines []string
	maxText := 0
	for _, item := range m.menuItems {
		if w := lipgloss.Width(item); w > maxText {
			maxText = w
		}
	}
	for i, item := range m.menuItems {
		style := menuItemStyle
		cursor := "  "
		if i == m.selected {
			style = menuSelectedStyle
			cursor = "> "
		}
		lineContent := cursor + style.Render(item)
		line := lipgloss.PlaceHorizontal(maxText+len(cursor)+2, lipgloss.Left, " "+lineContent+" ")
		lines = append(lines, line)
	}

	menuBlock := strings.Join(lines, "\n")
	if m.notice != "" {
		notice := lipgloss.NewStyle().Foreground(lipgloss.Color("#FF6B81")).Render(m.notice)
		menuBlock = menuBlock + "\n\n" + notice
	}

	if width <= 0 {
		return "\n\n" + menuBlock
	}

	blockWidth := maxText + 2 + 2 // cursor plus padding

	if width <= 0 {
		width = blockWidth
	}

	return "\n\n" + lipgloss.Place(width, lipgloss.Height(menuBlock), lipgloss.Center, lipgloss.Top, menuBlock)
}

func renderSummary(cfg config, width int) string {
	rows := []struct {
		label string
		val   string
	}{
		{"Wavelength", prettyValue(cfg.WAVE)},
		{"Date Start", prettyValue(cfg.START)},
		{"Date End", prettyValue(cfg.END)},
		{"Data Source", prettyValue(cfg.SOURCE)},
		{"Flare Class", prettyValue(cfg.FLARE_CLASS)},
		{"Comparator", prettyValue(cfg.COMPARATOR)},
		{"Last Email", prettyValue(cfg.DL_EMAIL)},
	}

	purple := lipgloss.Color("99")
	gray := lipgloss.Color("245")
	lightGray := lipgloss.Color("241")

	borderStyle := lipgloss.NewStyle().Foreground(purple)
	headerTextStyle := lipgloss.NewStyle().Foreground(purple).Bold(true)
	cellEven := lipgloss.NewStyle().Foreground(gray)
	cellOdd := lipgloss.NewStyle().Foreground(lightGray)

	pad := 1
	maxContent := lipgloss.Width("Summary")
	lineTexts := make([]string, len(rows))
	for i, row := range rows {
		line := row.label + ": " + row.val
		lineTexts[i] = line
		if w := lipgloss.Width(line); w > maxContent {
			maxContent = w
		}
	}

	cellWidth := maxContent + pad*2

	headerLine := headerTextStyle.
		Width(cellWidth).
		Align(lipgloss.Center).
		Render("SUMMARY")

	top := borderStyle.Render("┌" + strings.Repeat("─", cellWidth) + "┐")
	mid := borderStyle.Render("├" + strings.Repeat("─", cellWidth) + "┤")
	bottom := borderStyle.Render("└" + strings.Repeat("─", cellWidth) + "┘")

	var bodyLines []string
	for i, txt := range lineTexts {
		content := lipgloss.PlaceHorizontal(cellWidth, lipgloss.Left, strings.Repeat(" ", pad)+txt+strings.Repeat(" ", pad))
		styled := cellEven.Render(content)
		if i%2 == 1 {
			styled = cellOdd.Render(content)
		}
		bodyLines = append(bodyLines, borderStyle.Render("│")+styled+borderStyle.Render("│"))
	}

	tableLines := []string{
		top,
		borderStyle.Render("│") + headerLine + borderStyle.Render("│"),
		mid,
	}
	tableLines = append(tableLines, bodyLines...)
	tableLines = append(tableLines, bottom)

	tableStr := strings.Join(tableLines, "\n")
	if width <= 0 {
		return "\n" + tableStr
	}
	return "\n" + lipgloss.Place(width, len(tableLines), lipgloss.Center, lipgloss.Top, tableStr)
}

func prettyValue(val string) string {
	if strings.TrimSpace(val) == "" {
		return "<unset>"
	}
	return val
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func clampInt(v, min, max int) int {
	if v < min {
		return min
	}
	if v > max {
		return max
	}
	return v
}

func clamp(v, min, max float64) float64 {
	if v < min {
		return min
	}
	if v > max {
		return max
	}
	return v
}
