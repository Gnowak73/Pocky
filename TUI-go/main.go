package main

import (
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
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
			Foreground(statusBarStyle.GetBackground()).
			Background(lipgloss.Color("#FF7FB3")).
			Padding(0, 1).
			MarginRight(1).
			Bold(true)

	statusTextStyle = lipgloss.NewStyle().
			Inherit(statusBarStyle)

	statusHintStyle = lipgloss.NewStyle().
			Inherit(statusBarStyle).
			Foreground(lipgloss.Color("#D147FF")).
			Padding(0, 1)

	statusArrowStyle = lipgloss.NewStyle().
				Inherit(statusBarStyle)

	versionStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#8B5EDB")).
			Bold(true)

	menuItemStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#EAEAFF"))

	menuSelectedStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#F785D1"))

	menuHelpStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("241"))

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

	// Modes
	mode viewMode

	// Wavelength editor
	waveOptions  []waveOption
	waveSelected map[string]bool
	waveFocus    int
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

type viewMode int

const (
	modeMain viewMode = iota
	modeWavelength
)

type waveOption struct {
	code string
	desc string
}

func main() {
	logo, err := loadLogo()
	if err != nil {
		fmt.Println("pocky logo:", err)
		os.Exit(1)
	}

	cfg := loadConfig()
	m := newModel(logo, cfg)
	if err := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseAllMotion()).Start(); err != nil {
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

	waves := defaultWaveOptions()
	selected := parseWaves(cfg.WAVE, waves)

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
		logoLines:    logo,
		colored:      colored,
		cfg:          cfg,
		blockW:       blockW,
		menuItems:    menu,
		mode:         modeMain,
		waveOptions:  waves,
		waveSelected: selected,
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
		if m.mode == modeMain {
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
					switch m.menuItems[m.selected] {
					case "Edit Wavelength":
						m.mode = modeWavelength
						m.waveSelected = parseWaves(m.cfg.WAVE, m.waveOptions)
						m.waveFocus = 0
						m.notice = ""
					default:
						m.notice = fmt.Sprintf("Selected: %s (not implemented yet)", m.menuItems[m.selected])
					}
				}
			}
		} else if m.mode == modeWavelength {
			switch msg.String() {
			case "ctrl+c":
				return m, tea.Quit
			case "esc", "q":
				m.mode = modeMain
				m.notice = "Canceled wavelength edit"
			case "up", "k":
				if m.waveFocus > 0 {
					m.waveFocus--
				}
			case "down", "j":
				if m.waveFocus < len(m.waveOptions)-1 {
					m.waveFocus++
				}
			case " ":
				m.toggleWave(m.waveFocus)
			case "enter":
				m.cfg.WAVE = buildWaveValue(m.waveOptions, m.waveSelected)
				if err := saveConfig(m.cfg); err != nil {
					m.notice = fmt.Sprintf("Save failed: %v", err)
				} else {
					m.notice = "Wavelength saved"
				}
				m.mode = modeMain
			}
		}
	case tea.MouseMsg:
		if m.mode == modeMain {
			if msg.Button == tea.MouseButtonNone && msg.Action == tea.MouseActionMotion {
				if idx, ok := m.menuIndexAt(msg.X, msg.Y); ok {
					m.selected = idx
				}
			}
			switch msg.Button {
			case tea.MouseButtonWheelUp:
				if m.selected > 0 {
					m.selected--
				}
			case tea.MouseButtonWheelDown:
				if m.selected < len(m.menuItems)-1 {
					m.selected++
				}
			case tea.MouseButtonLeft:
				if idx, ok := m.menuIndexAt(msg.X, msg.Y); ok {
					m.selected = idx
					if msg.Action == tea.MouseActionRelease {
						switch m.menuItems[m.selected] {
						case "Edit Wavelength":
							m.mode = modeWavelength
							m.waveSelected = parseWaves(m.cfg.WAVE, m.waveOptions)
							m.waveFocus = 0
							m.notice = ""
						default:
							m.notice = fmt.Sprintf("Selected: %s (not implemented yet)", m.menuItems[m.selected])
						}
					}
				}
			}
		} else if m.mode == modeWavelength {
			if msg.Button == tea.MouseButtonNone && msg.Action == tea.MouseActionMotion {
				if idx, ok := m.waveIndexAt(msg.X, msg.Y); ok {
					m.waveFocus = idx
				}
			}
			if msg.Button == tea.MouseButtonLeft && msg.Action == tea.MouseActionRelease {
				if idx, ok := m.waveIndexAt(msg.X, msg.Y); ok {
					m.waveFocus = idx
					m.toggleWave(idx)
				}
			}
		}
	}
	return m, nil
}

func (m model) menuIndexAt(x, y int) (int, bool) {
	if y < 0 || x < 0 || len(m.menuItems) == 0 {
		return 0, false
	}

	if m.mode != modeMain {
		return 0, false
	}

	// Compute the rendered positions exactly as in View to align mouse coords with lines.
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

	header := box + "\n" + versionLine + summary
	menuTop := lipgloss.Height(header)
	menuHeight := lipgloss.Height(menu)
	if y < menuTop || y >= menuTop+menuHeight {
		return 0, false
	}

	relativeY := y - menuTop
	// renderMenu prefixes two blank lines before items; help/notice lines follow items.
	start := 1
	itemY := relativeY - start
	if itemY < 0 || itemY >= len(m.menuItems) {
		return 0, false
	}

	return itemY, true
}

func (m model) waveIndexAt(x, y int) (int, bool) {
	if m.mode != modeWavelength || y < 0 || x < 0 {
		return 0, false
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
	editor := renderWavelengthEditor(m, w)

	header := box + "\n" + versionLine + summary
	editorTop := lipgloss.Height(header)

	lines := strings.Split(editor, "\n")
	if y < editorTop || y >= editorTop+len(lines) {
		return 0, false
	}

	relativeY := y - editorTop
	rowIdx := -1
	rowsSeen := 0
	for i := 0; i < len(lines); i++ {
		trimmed := strings.TrimSpace(lines[i])
		if trimmed == "" || strings.HasPrefix(trimmed, "space toggle") || trimmed == "Select AIA Wavelength Channels" {
			continue
		}
		if strings.Contains(trimmed, "Å") && strings.Contains(trimmed, "[") {
			if relativeY <= i-1 { // adjust downward
				rowIdx = rowsSeen
				break
			}
			rowsSeen++
		}
	}

	if rowIdx < 0 || rowIdx >= len(m.waveOptions) {
		return 0, false
	}
	return rowIdx, true
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
	var body string
	var extraNotice string
	if m.mode == modeWavelength {
		body = summary + renderWavelengthEditor(m, w)
		if m.notice != "" {
			text := lipgloss.NewStyle().Foreground(lipgloss.Color("#FF6B81")).Render(m.notice)
			widthTarget := w
			if widthTarget <= 0 {
				widthTarget = lipgloss.Width(renderSummary(m.cfg, 0))
			}
			if widthTarget <= 0 {
				widthTarget = lipgloss.Width(text)
			}
			noticeLine := lipgloss.Place(widthTarget, 1, lipgloss.Center, lipgloss.Top, text)
			noticeLine = "  " + noticeLine
			extraNotice = "\n" + noticeLine
		}
	} else {
		body = summary + renderMenu(m, w)
	}

	status := renderStatus(w)
	if m.height > 0 {
		contentHeight := lipgloss.Height(box) + 1 + lipgloss.Height(body+extraNotice)
		gap := maxInt(m.height-contentHeight-lipgloss.Height(status), 0)
		return box + "\n" + versionLine + body + extraNotice + strings.Repeat("\n", gap) + status
	}

	return box + "\n" + versionLine + body + extraNotice + "\n" + status
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

func renderStatus(width int) string {
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
	hints := renderStaticGradientHint("q/esc to quit", available)

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

func renderStaticGradientHint(text string, available int) string {
	if available <= 0 {
		return ""
	}

	runes := []rune(text)
	if len(runes) == 0 {
		return ""
	}

	start, err := colorful.Hex("#D147FF") // lighter pinkish purple
	if err != nil {
		start = colorful.Color{}
	}
	end, err := colorful.Hex("#8B5EDB") // deeper purple
	if err != nil {
		end = colorful.Color{}
	}

	charStyle := statusHintStyle.Copy().Padding(0)
	var parts []string
	steps := len(runes)
	for i, r := range runes {
		t := 0.0
		if steps > 1 {
			t = float64(i) / float64(steps-1)
		}
		col := start.BlendHcl(end, t)
		parts = append(parts, charStyle.Foreground(lipgloss.Color(col.Hex())).Render(string(r)))
	}

	colored := strings.Join(parts, "")
	return statusHintStyle.Copy().
		Width(available).
		Align(lipgloss.Right).
		Render(colored)
}

func renderWavelengthEditor(m model, width int) string {
	title := summaryHeaderStyle.Copy().Bold(false).Render("Select AIA Wavelength Channels")
	divWidth := maxInt(lipgloss.Width(title)+6, 32)
	divider := lipgloss.NewStyle().Foreground(lipgloss.Color("#3A3A3A")).Render(strings.Repeat("─", divWidth))
	titleBlock := lipgloss.JoinVertical(lipgloss.Center, title, divider)

	codeStyle := lipgloss.NewStyle().Width(6)
	descStyle := lipgloss.NewStyle()
	checkStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1"))
	focusStyle := lipgloss.NewStyle().
		Background(lipgloss.Color("#2A262A"))

	var rows []string
	for i, opt := range m.waveOptions {
		check := "[ ]"
		if m.waveSelected[opt.code] {
			check = checkStyle.Render("[x]")
		}
		row := lipgloss.JoinHorizontal(
			lipgloss.Top,
			check,
			" ",
			codeStyle.Render(opt.code+"Å"),
			menuHelpStyle.Render("  │  "),
			descStyle.Render(opt.desc),
		)
		if i == m.waveFocus {
			row = focusStyle.Render(row)
		}
		rows = append(rows, row)
	}

	list := strings.Join(rows, "\n")
	list = " " + strings.ReplaceAll(list, "\n", "\n ")
	help := menuHelpStyle.Render("space toggle • enter save • esc cancel")

	block := lipgloss.JoinVertical(lipgloss.Left,
		titleBlock,
		"",
		list,
	)
	indent := func(s string) string {
		return " " + strings.ReplaceAll(s, "\n", "\n ")
	}

	if width <= 0 {
		return "\n\n" + indent(block) + "\n\n" + lipgloss.PlaceHorizontal(width, lipgloss.Center, help)
	}

	placed := lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	placed = indent(placed)
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	return "\n\n" + placed + "\n\n" + helpLine
}

func renderMenu(m model, width int) string {
	if m.mode != modeMain {
		return ""
	}
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
		cursorW := lipgloss.Width(cursor)
		if i == m.selected {
			style = menuSelectedStyle
			cursor = lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1")).Render("> ")
			cursorW = lipgloss.Width(cursor)
		}
		lineContent := cursor + style.Render(item)
		line := lipgloss.PlaceHorizontal(maxText+cursorW, lipgloss.Center, lineContent)
		lines = append(lines, line)
	}

	blockWidth := maxText + 2 // cursor + internal spacing

	menuBlock := strings.Join(lines, "\n")

	noticeLine := ""
	if m.notice != "" {
		notice := lipgloss.NewStyle().Foreground(lipgloss.Color("#FF6B81")).Render(m.notice)
		targetWidth := width
		if targetWidth <= 0 {
			targetWidth = blockWidth
		}
		noticeLine = lipgloss.Place(targetWidth, 1, lipgloss.Center, lipgloss.Top, notice)
	}

	helpText := "↑/k up • ↓/j down • enter submit"

	if width <= 0 {
		help := menuHelpStyle.Render(helpText)
		if noticeLine != "" {
			return "\n\n" + menuBlock + "\n\n" + noticeLine + "\n\n" + help
		}
		return "\n\n" + menuBlock + "\n\n" + help
	}

	placed := lipgloss.Place(width, lipgloss.Height(menuBlock), lipgloss.Center, lipgloss.Top, menuBlock)
	if noticeLine != "" {
		if strings.HasPrefix(noticeLine, " ") {
			noticeLine = noticeLine[1:]
		}
		if strings.HasPrefix(noticeLine, " ") {
			noticeLine = noticeLine[1:]
		}
	}
	help := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, menuHelpStyle.Render(helpText))
	var shifted []string
	for _, line := range strings.Split(placed, "\n") {
		if strings.HasPrefix(line, " ") {
			line = line[1:]
		}
		shifted = append(shifted, line)
	}
	block := "\n\n" + strings.Join(shifted, "\n")
	if noticeLine != "" {
		block += "\n\n" + noticeLine
	}
	return block + "\n\n" + help
}

func renderSummary(cfg config, width int) string {
	rows := []struct {
		label string
		val   string
	}{
		{"Wavelength", waveDisplay(cfg.WAVE)},
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
	cellWidth++

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
	tableWidth := lipgloss.Width(tableStr)
	w := width
	if w <= 0 {
		w = tableWidth
	}
	return "\n" + lipgloss.Place(w, len(tableLines), lipgloss.Center, lipgloss.Top, tableStr)
}

func prettyValue(val string) string {
	if strings.TrimSpace(val) == "" {
		return "<unset>"
	}
	return val
}

// waveDisplay collapses consecutive wavelengths into ranges, mirroring shell UI.
func waveDisplay(val string) string {
	val = strings.TrimSpace(val)
	if val == "" {
		return "<unset>"
	}

	order := []string{"94", "131", "171", "193", "211", "304", "335", "1600", "1700", "4500"}
	idx := make(map[string]int)
	for i, v := range order {
		idx[v] = i
	}

	parts := strings.Split(val, ",")
	var valid []string
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if _, ok := idx[p]; ok {
			valid = append(valid, p)
		}
	}
	if len(valid) == 0 {
		return val
	}

	sort.Slice(valid, func(i, j int) bool {
		return idx[valid[i]] < idx[valid[j]]
	})

	// collapse consecutive
	var out []string
	start := valid[0]
	prev := start
	for i := 1; i < len(valid); i++ {
		cur := valid[i]
		if idx[cur] == idx[prev]+1 {
			prev = cur
			continue
		}
		if start == prev {
			out = append(out, start)
		} else {
			out = append(out, fmt.Sprintf("%s-%s", start, prev))
		}
		start = cur
		prev = cur
	}
	if start == prev {
		out = append(out, start)
	} else {
		out = append(out, fmt.Sprintf("%s-%s", start, prev))
	}

	return strings.Join(out, ",")
}

func defaultWaveOptions() []waveOption {
	return []waveOption{
		{"94", "Fe XVIII (hot flares)"},
		{"131", "Fe VIII / Fe XXI"},
		{"171", "Fe IX (quiet corona)"},
		{"193", "Fe XII / Fe XXIV"},
		{"211", "Fe XIV (2 MK loops)"},
		{"304", "He II (chromosphere)"},
		{"335", "Fe XVI (2.5 MK)"},
		{"1600", "C IV / continuum"},
		{"1700", "continuum (photo.)"},
		{"4500", "white-light"},
	}
}

func parseWaves(val string, opts []waveOption) map[string]bool {
	selected := make(map[string]bool)
	if strings.TrimSpace(val) == "" {
		return selected
	}
	known := make(map[string]struct{})
	for _, o := range opts {
		known[o.code] = struct{}{}
	}
	for _, part := range strings.Split(val, ",") {
		p := strings.TrimSpace(part)
		if _, ok := known[p]; ok {
			selected[p] = true
		}
	}
	return selected
}

func buildWaveValue(opts []waveOption, sel map[string]bool) string {
	var parts []string
	for _, o := range opts {
		if sel[o.code] {
			parts = append(parts, o.code)
		}
	}
	return strings.Join(parts, ",")
}

func saveConfig(cfg config) error {
	paths := []string{
		".vars.env",
		filepath.Join("..", ".vars.env"),
	}

	target := paths[0]
	for _, p := range paths {
		if _, err := os.Stat(p); err == nil {
			target = p
			break
		}
	}

	var b strings.Builder
	fmt.Fprintf(&b, "WAVE=\"%s\"\n", cfg.WAVE)
	fmt.Fprintf(&b, "START=\"%s\"\n", cfg.START)
	fmt.Fprintf(&b, "END=\"%s\"\n", cfg.END)
	fmt.Fprintf(&b, "SOURCE=\"%s\"\n", cfg.SOURCE)
	fmt.Fprintf(&b, "FLARE_CLASS=\"%s\"\n", cfg.FLARE_CLASS)
	fmt.Fprintf(&b, "COMPARATOR=\"%s\"\n", cfg.COMPARATOR)
	fmt.Fprintf(&b, "DL_EMAIL=\"%s\"\n", cfg.DL_EMAIL)

	tmp := target + ".tmp"
	if err := os.WriteFile(tmp, []byte(b.String()), 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, target)
}

func (m *model) toggleWave(idx int) {
	if idx < 0 || idx >= len(m.waveOptions) {
		return
	}
	code := m.waveOptions[idx].code
	m.waveSelected[code] = !m.waveSelected[code]
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
