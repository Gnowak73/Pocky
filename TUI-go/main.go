package main

import (
	"bufio"
	"errors"
	"fmt"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/table"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	lgtbl "github.com/charmbracelet/lipgloss/table"
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
	noticeSet int

	// Modes
	mode viewMode

	// Wavelength editor
	waveOptions  []waveOption
	waveSelected map[string]bool
	waveFocus    int

	// Flare filter editor
	flareCompOptions  []string
	flareCompMap      map[string]string
	flareClassLetters []string
	flareMagnitudes   []string
	flareFocus        int // 0=comp,1=letter,2=mag
	flareCompIdx      int
	flareLetterIdx    int
	flareMagIdx       int
	flareFocusFrame   int

	// Flare selection
	flareList      []flareEntry
	flareHeader    string
	flareSelected  map[int]bool
	flareCursor    int
	flareOffset    int
	flareLoading   bool
	flareLoadError string
	flareTable     table.Model

	// Cache submenu
	cacheMenuOpen   bool
	cacheMenuItems  []string
	cacheSelected   int
	cacheOpenFrame  int
	cacheRows       []cacheRow
	cacheHeader     string
	cachePick       map[int]bool
	cacheCursor     int
	cacheOffset     int
	cacheViewport   viewport.Model
	cacheContent    string
	cachePaneFocus  int // 0=table,1=side
	cacheSideCursor int
	cacheSideOffset int

	// Loading animation
	spinFrames []string
	spinIndex  int

	// Date editor
	dateStart string
	dateEnd   string
	dateFocus int
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
type flaresLoadedMsg struct {
	entries []flareEntry
	header  string
	err     error
}

type viewMode int

const (
	modeMain viewMode = iota
	modeWavelength
	modeDateRange
	modeFlare
	modeSelectFlares
	modeCacheView
	modeCacheDelete
)

type waveOption struct {
	code string
	desc string
}

type flareEntry struct {
	desc  string
	class string
	start string
	end   string
	coord string
	full  string
}

type cacheRow struct {
	desc  string
	class string
	start string
	end   string
	coord string
	wave  string
	full  string
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

func flareViewHeight(m model) int {
	if len(m.flareList) == 0 {
		return 0
	}
	return maxInt(7, minInt(12, len(m.flareList)))
}

func cacheViewHeight(m model) int {
	if len(m.cacheRows) == 0 {
		return 0
	}
	return maxInt(7, minInt(25, len(m.cacheRows)))
}

func (m model) styledFlareRows() []table.Row {
	if len(m.flareList) == 0 {
		return nil
	}
	rows := make([]table.Row, 0, len(m.flareList))
	for i, entry := range m.flareList {
		check := "[ ]"
		if m.flareSelected[i] {
			check = "[x]"
		}
		rows = append(rows, table.Row{check, entry.class, entry.start, entry.end, entry.coord})
	}
	return rows
}

func (m *model) rebuildFlareTable() {
	if len(m.flareList) == 0 {
		m.flareTable = table.Model{}
		return
	}

	wSel, wClass, wStart, wEnd, wCoord := flareTableWidths(*m)
	columns := []table.Column{
		{Title: "SEL", Width: wSel},
		{Title: "CLASS", Width: wClass},
		{Title: "START", Width: wStart},
		{Title: "END", Width: wEnd},
		{Title: "COORDINATES", Width: wCoord},
	}

	rows := m.styledFlareRows()
	height := maxInt(7, minInt(12, len(rows)))
	t := table.New(
		table.WithColumns(columns),
		table.WithRows(rows),
		table.WithHeight(height),
		table.WithFocused(true),
	)
	s := table.DefaultStyles()
	s.Header = s.Header.
		BorderStyle(lipgloss.NormalBorder()).
		BorderForeground(lipgloss.Color("238")).
		BorderBottom(true).
		Foreground(lipgloss.Color("252")).
		Bold(true).
		PaddingLeft(1).
		PaddingRight(1)
	s.Selected = s.Selected.
		Foreground(lipgloss.Color("245")).
		Background(lipgloss.Color("")).
		Bold(false).
		PaddingLeft(1).
		PaddingRight(1)
	s.Cell = s.Cell.
		Align(lipgloss.Left).
		Foreground(lipgloss.Color("245")).
		PaddingLeft(1).
		PaddingRight(1)
	t.SetStyles(s)
	t.SetCursor(m.flareCursor)
	m.flareTable = t
}

func (m *model) updateFlareTableRows() {
	if len(m.flareList) == 0 || m.flareTable.Columns() == nil {
		return
	}
	rows := m.styledFlareRows()
	m.flareTable.SetRows(rows)
	m.flareTable.SetCursor(m.flareCursor)
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
	cacheMenu := []string{
		"View Cache",
		"Delete Rows",
		"Clear Cache",
		"Back",
	}

	compOpts, compMap := defaultComparatorOptions()
	letters := defaultClassLetters()
	mags := defaultMagnitudes()
	compIdx, letterIdx, magIdx := parseFlareSelection(cfg, compOpts, compMap, letters, mags)

	return model{
		logoLines:         logo,
		colored:           colored,
		cfg:               cfg,
		blockW:            blockW,
		menuItems:         menu,
		mode:              modeMain,
		waveOptions:       waves,
		waveSelected:      selected,
		flareCompOptions:  compOpts,
		flareCompMap:      compMap,
		flareClassLetters: letters,
		flareMagnitudes:   mags,
		flareCompIdx:      compIdx,
		flareLetterIdx:    letterIdx,
		flareMagIdx:       magIdx,
		flareFocusFrame:   0,
		flareSelected:     make(map[int]bool),
		spinFrames:        []string{"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"},
		flareOffset:       0,
		cacheMenuItems:    cacheMenu,
		cachePick:         make(map[int]bool),
		cacheViewport:     viewport.New(80, 20),
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
		if msg.Width > 0 && msg.Height > 0 {
			m.cacheViewport.Width = maxInt(msg.Width-6, 20)
			m.cacheViewport.Height = maxInt(msg.Height-10, 8)
			if m.mode == modeCacheView && m.cacheContent != "" {
				m.cacheViewport.SetContent(m.cacheContent)
			}
		}
	case tickMsg:
		m.frame++
		m.colored = colorizeLogo(m.logoLines, m.blockW, m.frame)
		if m.notice != "" && m.noticeSet > 0 && m.frame-m.noticeSet > 19 {
			m.notice = ""
		}
		if m.flareLoading && len(m.spinFrames) > 0 {
			m.spinIndex = (m.spinIndex + 1) % len(m.spinFrames)
		}
		return m, tick()
	case flaresLoadedMsg:
		m.flareLoading = false
		if msg.err != nil {
			m.flareLoadError = msg.err.Error()
			m.notice = m.flareLoadError
			m.noticeSet = m.frame
			m.mode = modeMain
			return m, nil
		}
		m.flareList = msg.entries
		m.flareHeader = msg.header
		m.flareSelected = make(map[int]bool)
		if len(m.flareList) == 0 {
			m.notice = "No flares found."
			m.noticeSet = m.frame
			m.mode = modeMain
			return m, nil
		}
		m.flareCursor = 0
		m.flareOffset = 0
		m.rebuildFlareTable()
		return m, nil
	case tea.KeyMsg:
		var cmd tea.Cmd
		if m.mode == modeMain {
			if m.cacheMenuOpen {
				switch msg.String() {
				case "ctrl+c":
					return m, tea.Quit
				case "esc", "left", "h", "q":
					m.cacheMenuOpen = false
					return m, nil
				case "up", "k":
					if m.cacheSelected > 0 {
						m.cacheSelected--
					}
					return m, nil
				case "down", "j":
					if m.cacheSelected < len(m.cacheMenuItems)-1 {
						m.cacheSelected++
					}
					return m, nil
				case "enter", " ":
					if m.cacheSelected >= 0 && m.cacheSelected < len(m.cacheMenuItems) {
						switch m.cacheMenuItems[m.cacheSelected] {
						case "Back":
							m.cacheMenuOpen = false
							m.notice = "Cache menu closed"
							m.noticeSet = m.frame
						case "View Cache":
							header, rows, err := loadCache()
							m.cacheMenuOpen = false
							if err != nil {
								header = "description\tflare_class\tstart\tend\tcoordinates\twavelength"
								rows = nil
							}
							m.cacheHeader = header
							m.cacheRows = rows
							m.cacheContent = renderCacheTableString(rows, m.width)
							m.cachePaneFocus = 0
							m.cacheSideCursor = 0
							m.cacheSideOffset = 0
							if m.width > 0 && m.height > 0 {
								m.cacheViewport.Width = maxInt(m.width-6, 20)
								m.cacheViewport.Height = maxInt(m.height-10, 8)
							} else {
								m.cacheViewport.Width = 80
								m.cacheViewport.Height = 20
							}
							m.cacheViewport.SetContent(m.cacheContent)
							m.mode = modeCacheView
							return m, nil
						case "Delete Rows":
							header, rows, err := loadCache()
							m.cacheMenuOpen = false
							if err != nil || len(rows) == 0 {
								m.notice = "Cache empty or missing"
								m.noticeSet = m.frame
								return m, nil
							}
							m.cacheHeader = header
							m.cacheRows = rows
							m.cacheCursor = 0
							m.cacheOffset = 0
							m.cachePick = make(map[int]bool)
							m.mode = modeCacheDelete
							return m, nil
						case "Clear Cache":
							m.cacheMenuOpen = false
							if _, err := clearCacheFile(); err != nil {
								m.notice = fmt.Sprintf("Clear failed: %v", err)
							} else {
								m.notice = "Cleared flare cache"
							}
							m.noticeSet = m.frame
						}
					}
					return m, nil
				}
			}

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
						m.cacheMenuOpen = false
						m.mode = modeWavelength
						m.waveSelected = parseWaves(m.cfg.WAVE, m.waveOptions)
						m.waveFocus = 0
						m.notice = ""
						m.noticeSet = m.frame
					case "Edit Date Range":
						m.cacheMenuOpen = false
						m.mode = modeDateRange
						m.dateStart = ""
						m.dateEnd = ""
						m.dateFocus = 0
						m.notice = ""
						m.noticeSet = m.frame
					case "Edit Flare Class Filter":
						m.cacheMenuOpen = false
						m.mode = modeFlare
						m.flareCompIdx, m.flareLetterIdx, m.flareMagIdx = parseFlareSelection(m.cfg, m.flareCompOptions, m.flareCompMap, m.flareClassLetters, m.flareMagnitudes)
						m.flareFocus = 0
						m.flareFocusFrame = m.frame
						m.notice = ""
						m.noticeSet = m.frame
					case "Select Flares":
						if strings.TrimSpace(m.cfg.START) == "" || strings.TrimSpace(m.cfg.END) == "" {
							m.notice = "Set a date range first."
							m.noticeSet = m.frame
							break
						}
						if strings.TrimSpace(m.cfg.WAVE) == "" {
							m.notice = "Select at least one wavelength first."
							m.noticeSet = m.frame
							break
						}
						if strings.TrimSpace(m.cfg.COMPARATOR) == "" {
							m.notice = "Set a comparator first."
							m.noticeSet = m.frame
							break
						}
						m.cacheMenuOpen = false
						m.mode = modeSelectFlares
						m.flareLoading = true
						m.flareLoadError = ""
						m.flareSelected = make(map[int]bool)
						m.flareCursor = 0
						m.flareOffset = 0
						m.flareList = nil
						m.flareHeader = ""
						m.notice = ""
						m.noticeSet = 0
						cmd = loadFlaresCmd(m.cfg)
					case "Cache Options":
						m.cacheMenuOpen = true
						m.cacheOpenFrame = m.frame
						m.cacheSelected = 0
						m.notice = ""
						m.noticeSet = m.frame
					default:
						m.notice = fmt.Sprintf("Selected: %s (not implemented yet)", m.menuItems[m.selected])
						m.noticeSet = m.frame
					}
				}
			}
		} else if m.mode == modeCacheView {
			switch msg.String() {
			case "ctrl+c":
				return m, tea.Quit
			case "esc", "q":
				m.mode = modeMain
				m.notice = "Cache view closed"
				m.noticeSet = m.frame
				return m, nil
			case "delete", "backspace", "ctrl+d":
				// enter delete mode directly
				m.mode = modeCacheDelete
				m.cacheCursor = 0
				m.cacheOffset = 0
				m.cachePick = make(map[int]bool)
				return m, nil
			}
			var vpCmd tea.Cmd
			m.cacheViewport, vpCmd = m.cacheViewport.Update(msg)
			return m, vpCmd
		} else if m.mode == modeCacheDelete {
			switch msg.String() {
			case "ctrl+c":
				return m, tea.Quit
			case "esc", "q", "left", "h":
				m.mode = modeMain
				m.notice = "Canceled cache deletion"
				m.noticeSet = m.frame
			case "up", "k":
				if m.cacheCursor > 0 {
					m.cacheCursor--
					m.ensureCacheVisible()
				}
			case "down", "j":
				if m.cacheCursor < len(m.cacheRows)-1 {
					m.cacheCursor++
					m.ensureCacheVisible()
				}
			case "pgup", "b":
				m.cacheCursor = maxInt(0, m.cacheCursor-5)
				m.ensureCacheVisible()
			case "pgdown", "f":
				m.cacheCursor = minInt(len(m.cacheRows)-1, m.cacheCursor+5)
				m.ensureCacheVisible()
			case " ":
				if m.cacheCursor >= 0 && m.cacheCursor < len(m.cacheRows) {
					m.cachePick[m.cacheCursor] = !m.cachePick[m.cacheCursor]
				}
			case "enter":
				if len(m.cachePick) == 0 {
					m.mode = modeMain
					m.notice = "No rows selected."
					m.noticeSet = m.frame
					break
				}
				if err := saveCachePruned(m.cacheHeader, m.cacheRows, m.cachePick); err != nil {
					m.notice = fmt.Sprintf("Delete failed: %v", err)
				} else {
					m.notice = fmt.Sprintf("Deleted %d rows", len(m.cachePick))
					// Reload cache into viewport after deletion
					header, rows, err := loadCache()
					if err == nil {
						m.cacheHeader = header
						m.cacheRows = rows
						m.cachePick = make(map[int]bool)
						m.cacheContent = renderCacheTableString(rows, m.width)
						if m.width > 0 && m.height > 0 {
							m.cacheViewport.Width = maxInt(m.width-6, 20)
							m.cacheViewport.Height = maxInt(m.height-10, 8)
						}
						m.cacheViewport.SetContent(m.cacheContent)
					} else {
						m.cacheRows = nil
						m.cachePick = make(map[int]bool)
					}
				}
				m.noticeSet = m.frame
				m.mode = modeMain
			}
			return m, nil
		} else if m.mode == modeWavelength {
			switch msg.String() {
			case "ctrl+c":
				return m, tea.Quit
			case "ctrl+a":
				allSelected := true
				for _, opt := range m.waveOptions {
					if !m.waveSelected[opt.code] {
						allSelected = false
						break
					}
				}
				next := true
				if allSelected {
					next = false
				}
				for _, opt := range m.waveOptions {
					m.waveSelected[opt.code] = next
				}
			case "esc", "q":
				m.mode = modeMain
				m.notice = "Canceled wavelength edit"
				m.noticeSet = m.frame
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
					m.noticeSet = m.frame
				} else {
					m.notice = "Wavelength saved"
					m.noticeSet = m.frame
				}
				m.mode = modeMain
			}
		} else if m.mode == modeDateRange {
			handled := true
			switch msg.String() {
			case "ctrl+c":
				return m, tea.Quit
			case "esc", "q":
				m.mode = modeMain
				m.notice = "Canceled date edit"
				m.noticeSet = m.frame
			case "tab", "down":
				m.dateFocus = 1
			case "shift+tab", "up":
				m.dateFocus = 0
			case "enter":
				start := strings.TrimSpace(m.dateStart)
				end := strings.TrimSpace(m.dateEnd)
				if start == "" {
					start = strings.TrimSpace(m.cfg.START)
				}
				if end == "" {
					end = strings.TrimSpace(m.cfg.END)
				}
				if !validDate(start) || !validDate(end) {
					m.notice = "Dates must be YYYY-MM-DD"
					m.noticeSet = m.frame
					break
				}
				if !chronological(start, end) {
					m.notice = "Start must be on/before End"
					m.noticeSet = m.frame
					break
				}
				m.cfg.START = start
				m.cfg.END = end
				if err := saveConfig(m.cfg); err != nil {
					m.notice = fmt.Sprintf("Save failed: %v", err)
					m.noticeSet = m.frame
					break
				}
				m.notice = "Date range saved"
				m.noticeSet = m.frame
				m.mode = modeMain
			case "backspace", "delete":
				if m.dateFocus == 0 {
					if len(m.dateStart) > 0 {
						m.dateStart = m.dateStart[:len(m.dateStart)-1]
					}
				} else {
					if len(m.dateEnd) > 0 {
						m.dateEnd = m.dateEnd[:len(m.dateEnd)-1]
					}
				}
			default:
				handled = false
			}
			if !handled {
				if len(msg.Runes) > 0 {
					var runes []rune
					for _, r := range msg.Runes {
						if (r >= '0' && r <= '9') || r == '-' {
							runes = append(runes, r)
						}
					}
					if len(runes) > 0 {
						target := &m.dateStart
						if m.dateFocus == 1 {
							target = &m.dateEnd
						}
						if len(*target) < len("2006-01-02") {
							*target += string(runes)
							if len(*target) > len("2006-01-02") {
								*target = (*target)[:len("2006-01-02")]
							}
						}
					}
				}
			}
		} else if m.mode == modeFlare {
			switch msg.String() {
			case "ctrl+c":
				return m, tea.Quit
			case "esc", "q":
				m.mode = modeMain
				m.notice = "Canceled flare filter edit"
				m.noticeSet = m.frame
			case "tab", "right", "l":
				m.flareFocus = (m.flareFocus + 1) % 3
				m.flareFocusFrame = m.frame
			case "shift+tab", "left", "h":
				m.flareFocus--
				if m.flareFocus < 0 {
					m.flareFocus = 2
				}
				m.flareFocusFrame = m.frame
			case "up", "k":
				switch m.flareFocus {
				case 0:
					if m.flareCompIdx > 0 {
						m.flareCompIdx--
					}
				case 1:
					if m.flareLetterIdx > 0 {
						m.flareLetterIdx--
					}
				case 2:
					if m.flareMagIdx > 0 {
						m.flareMagIdx--
					}
				}
			case "down", "j":
				switch m.flareFocus {
				case 0:
					if m.flareCompIdx < len(m.flareCompOptions)-1 {
						m.flareCompIdx++
					}
				case 1:
					if m.flareLetterIdx < len(m.flareClassLetters)-1 {
						m.flareLetterIdx++
					}
				case 2:
					if m.flareMagIdx < len(m.flareMagnitudes)-1 {
						m.flareMagIdx++
					}
				}
			case "enter":
				comp := m.flareCompOptions[m.flareCompIdx]
				compVal := m.flareCompMap[comp]
				if compVal == "" {
					compVal = comp
				}
				letter := m.flareClassLetters[m.flareLetterIdx]
				mag := m.flareMagnitudes[m.flareMagIdx]
				if compVal == "All" {
					m.cfg.COMPARATOR = "All"
					m.cfg.FLARE_CLASS = "Any"
				} else {
					m.cfg.COMPARATOR = compVal
					m.cfg.FLARE_CLASS = fmt.Sprintf("%s%s", letter, mag)
				}
				if err := saveConfig(m.cfg); err != nil {
					m.notice = fmt.Sprintf("Save failed: %v", err)
					m.noticeSet = m.frame
					break
				}
				m.notice = "Flare filter saved"
				m.noticeSet = m.frame
				m.mode = modeMain
			}
		} else if m.mode == modeSelectFlares {
			switch msg.String() {
			case "ctrl+c":
				return m, tea.Quit
			case "esc", "q":
				m.mode = modeMain
				m.notice = "Canceled flare selection"
				m.noticeSet = m.frame
			case " ":
				if m.flareCursor >= 0 && m.flareCursor < len(m.flareList) {
					m.flareSelected[m.flareCursor] = !m.flareSelected[m.flareCursor]
				}
			case "enter":
				if len(m.flareSelected) == 0 {
					m.notice = "No flares selected."
					m.noticeSet = m.frame
					m.mode = modeMain
					break
				}
				if err := saveFlareSelection(m.flareHeader, m.flareList, m.flareSelected); err != nil {
					m.notice = fmt.Sprintf("Save failed: %v", err)
					m.noticeSet = m.frame
				} else {
					m.notice = fmt.Sprintf("Saved %d flares", len(m.flareSelected))
					m.noticeSet = m.frame
				}
				m.mode = modeMain
			case "up", "k":
				if m.flareCursor > 0 {
					m.flareCursor--
				}
				m.ensureFlareVisible()
			case "down", "j":
				if m.flareCursor < len(m.flareList)-1 {
					m.flareCursor++
				}
				m.ensureFlareVisible()
			default:
				// ignore other keys in flare selection
			}
			return m, nil
		} else if m.mode == modeCacheView {
			switch msg.Type {
			case tea.KeyCtrlC:
				return m, tea.Quit
			case tea.KeyEsc:
				m.mode = modeMain
				m.notice = "Cache view closed"
				m.noticeSet = m.frame
				return m, nil
			case tea.KeyDelete, tea.KeyBackspace:
				m.mode = modeCacheDelete
				m.cacheCursor = 0
				m.cacheOffset = 0
				m.cachePick = make(map[int]bool)
				return m, nil
			}

			switch msg.String() {
			case "q":
				m.mode = modeMain
				m.notice = "Cache view closed"
				m.noticeSet = m.frame
				return m, nil
			case "ctrl+d":
				m.mode = modeCacheDelete
				m.cacheCursor = 0
				m.cacheOffset = 0
				m.cachePick = make(map[int]bool)
				return m, nil
			}

			var cmd tea.Cmd
			m.cacheViewport, cmd = m.cacheViewport.Update(msg)
			return m, cmd
		} else if m.mode == modeCacheDelete {
			switch msg.String() {
			case "ctrl+c":
				return m, tea.Quit
			case "esc", "q", "left", "h":
				m.mode = modeMain
				m.notice = "Canceled cache deletion"
				m.noticeSet = m.frame
			case "up", "k":
				if m.cacheCursor > 0 {
					m.cacheCursor--
				}
				m.ensureCacheVisible()
			case "down", "j":
				if m.cacheCursor < len(m.cacheRows)-1 {
					m.cacheCursor++
				}
				m.ensureCacheVisible()
			case " ":
				if m.cacheCursor >= 0 && m.cacheCursor < len(m.cacheRows) {
					m.cachePick[m.cacheCursor] = !m.cachePick[m.cacheCursor]
				}
			case "enter":
				if len(m.cachePick) == 0 {
					m.mode = modeMain
					m.notice = "No rows selected."
					m.noticeSet = m.frame
					break
				}
				if err := saveCachePruned(m.cacheHeader, m.cacheRows, m.cachePick); err != nil {
					m.notice = fmt.Sprintf("Delete failed: %v", err)
				} else {
					m.notice = fmt.Sprintf("Deleted %d rows", len(m.cachePick))
					// Reload cache into viewport after deletion
					header, rows, err := loadCache()
					if err == nil {
						m.cacheHeader = header
						m.cacheRows = rows
						m.cachePick = make(map[int]bool)
						m.cacheContent = renderCacheTableString(rows, m.width)
						if m.width > 0 && m.height > 0 {
							m.cacheViewport.Width = maxInt(m.width-6, 20)
							m.cacheViewport.Height = maxInt(m.height-10, 8)
						}
						m.cacheViewport.SetContent(m.cacheContent)
					} else {
						m.cacheRows = nil
						m.cachePick = make(map[int]bool)
					}
				}
				m.noticeSet = m.frame
				m.mode = modeMain
			}
			return m, nil
		}
		return m, cmd
	case tea.MouseMsg:
		var cmd tea.Cmd
		if m.mode == modeMain {
			if m.cacheMenuOpen {
				switch msg.Button {
				case tea.MouseButtonWheelUp:
					if m.cacheSelected > 0 {
						m.cacheSelected--
					}
				case tea.MouseButtonWheelDown:
					if m.cacheSelected < len(m.cacheMenuItems)-1 {
						m.cacheSelected++
					}
				case tea.MouseButtonNone:
					if idx, ok := m.cacheMenuIndexAt(msg.X, msg.Y); ok {
						m.cacheSelected = idx
					}
				case tea.MouseButtonLeft:
					if msg.Action == tea.MouseActionRelease {
						// trigger current cache action
						switch m.cacheMenuItems[m.cacheSelected] {
						case "Back":
							m.cacheMenuOpen = false
							m.notice = "Cache menu closed"
							m.noticeSet = m.frame
						case "View Cache":
							header, rows, err := loadCache()
							m.cacheMenuOpen = false
							if err != nil {
								header = "description\tflare_class\tstart\tend\tcoordinates\twavelength"
								rows = nil
							}
							m.cacheHeader = header
							m.cacheRows = rows
							m.cacheContent = renderCacheTableString(rows, m.width)
							m.cachePaneFocus = 0
							m.cacheSideCursor = 0
							m.cacheSideOffset = 0
							if m.width > 0 && m.height > 0 {
								m.cacheViewport.Width = maxInt(m.width-6, 20)
								m.cacheViewport.Height = maxInt(m.height-10, 8)
							} else {
								m.cacheViewport.Width = 80
								m.cacheViewport.Height = 20
							}
							m.cacheViewport.SetContent(m.cacheContent)
							m.mode = modeCacheView
						case "Delete Rows":
							header, rows, err := loadCache()
							m.cacheMenuOpen = false
							if err != nil || len(rows) == 0 {
								m.notice = "Cache empty or missing"
								m.noticeSet = m.frame
								return m, nil
							}
							m.cacheHeader = header
							m.cacheRows = rows
							m.cacheCursor = 0
							m.cacheOffset = 0
							m.cachePick = make(map[int]bool)
							m.mode = modeCacheDelete
						case "Clear Cache":
							m.cacheMenuOpen = false
							if _, err := clearCacheFile(); err != nil {
								m.notice = fmt.Sprintf("Clear failed: %v", err)
							} else {
								m.notice = "Cleared flare cache"
							}
							m.noticeSet = m.frame
						}
					}
				}
				return m, nil
			}
			if msg.Button == tea.MouseButtonNone && msg.Action == tea.MouseActionMotion {
				if idx, ok := m.cacheMenuIndexAt(msg.X, msg.Y); ok {
					m.cacheSelected = idx
					return m, nil
				}
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
							m.cacheMenuOpen = false
							m.mode = modeWavelength
							m.waveSelected = parseWaves(m.cfg.WAVE, m.waveOptions)
							m.waveFocus = 0
							m.notice = ""
						case "Edit Date Range":
							m.cacheMenuOpen = false
							m.mode = modeDateRange
							m.dateStart = ""
							m.dateEnd = ""
							m.dateFocus = 0
							m.notice = ""
						case "Edit Flare Class Filter":
							m.cacheMenuOpen = false
							m.mode = modeFlare
							m.flareCompIdx, m.flareLetterIdx, m.flareMagIdx = parseFlareSelection(m.cfg, m.flareCompOptions, m.flareCompMap, m.flareClassLetters, m.flareMagnitudes)
							m.flareFocus = 0
							m.flareFocusFrame = m.frame
							m.notice = ""
						case "Select Flares":
							m.cacheMenuOpen = false
							if strings.TrimSpace(m.cfg.START) == "" || strings.TrimSpace(m.cfg.END) == "" {
								m.notice = "Set a date range first."
								m.noticeSet = m.frame
								break
							}
							if strings.TrimSpace(m.cfg.WAVE) == "" {
								m.notice = "Select at least one wavelength first."
								m.noticeSet = m.frame
								break
							}
							if strings.TrimSpace(m.cfg.COMPARATOR) == "" {
								m.notice = "Set a comparator first."
								m.noticeSet = m.frame
								break
							}
							m.mode = modeSelectFlares
							m.flareLoading = true
							m.flareLoadError = ""
							m.flareSelected = make(map[int]bool)
							m.flareCursor = 0
							m.flareList = nil
							m.flareHeader = ""
							m.notice = ""
							m.noticeSet = 0
							return m, loadFlaresCmd(m.cfg)
						case "Cache Options":
							m.cacheMenuOpen = true
							m.cacheOpenFrame = m.frame
							m.cacheSelected = 0
							m.notice = ""
						default:
							m.notice = fmt.Sprintf("Selected: %s (not implemented yet)", m.menuItems[m.selected])
							m.noticeSet = m.frame
						}
					}
				}
			}
		} else if m.mode == modeCacheView {
			switch msg.Button {
			case tea.MouseButtonWheelUp:
				if m.cachePaneFocus == 0 {
					var vpCmd tea.Cmd
					m.cacheViewport, vpCmd = m.cacheViewport.Update(msg)
					return m, vpCmd
				}
				if m.cacheSideCursor > 0 {
					m.cacheSideCursor--
					if m.cacheSideCursor < m.cacheSideOffset {
						m.cacheSideOffset = m.cacheSideCursor
					}
				}
			case tea.MouseButtonWheelDown:
				if m.cachePaneFocus == 0 {
					var vpCmd tea.Cmd
					m.cacheViewport, vpCmd = m.cacheViewport.Update(msg)
					return m, vpCmd
				}
				if m.cacheSideCursor < len(m.cacheRows)-1 {
					m.cacheSideCursor++
					if m.cacheSideCursor >= m.cacheSideOffset+10 {
						m.cacheSideOffset = m.cacheSideCursor - 9
					}
				}
			case tea.MouseButtonLeft:
				// left click moves focus to side list; use keyboard to return
				if msg.Action == tea.MouseActionRelease {
					m.cachePaneFocus = 1
				}
			default:
				if m.cachePaneFocus == 0 {
					var vpCmd tea.Cmd
					m.cacheViewport, vpCmd = m.cacheViewport.Update(msg)
					return m, vpCmd
				}
			}
			return m, nil
		} else if m.mode == modeCacheDelete {
			switch msg.Button {
			case tea.MouseButtonWheelUp:
				if m.cacheCursor > 0 {
					m.cacheCursor--
					m.ensureCacheVisible()
				}
			case tea.MouseButtonWheelDown:
				if m.cacheCursor < len(m.cacheRows)-1 {
					m.cacheCursor++
					m.ensureCacheVisible()
				}
			case tea.MouseButtonLeft:
				if msg.Action == tea.MouseActionRelease {
					// Toggle current row (acts like space)
					if m.cacheCursor >= 0 && m.cacheCursor < len(m.cacheRows) {
						m.cachePick[m.cacheCursor] = !m.cachePick[m.cacheCursor]
					}
				}
			}
			return m, nil
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
		} else if m.mode == modeFlare {
			col, row, ok := m.flareHit(msg.X, msg.Y)
			if msg.Button == tea.MouseButtonNone && msg.Action == tea.MouseActionMotion && ok {
				m.flareFocus = col
			}
			switch msg.Button {
			case tea.MouseButtonWheelUp:
				switch m.flareFocus {
				case 0:
					if m.flareCompIdx > 0 {
						m.flareCompIdx--
					}
				case 1:
					if m.flareLetterIdx > 0 {
						m.flareLetterIdx--
					}
				case 2:
					if m.flareMagIdx > 0 {
						m.flareMagIdx--
					}
				}
			case tea.MouseButtonWheelDown:
				switch m.flareFocus {
				case 0:
					if m.flareCompIdx < len(m.flareCompOptions)-1 {
						m.flareCompIdx++
					}
				case 1:
					if m.flareLetterIdx < len(m.flareClassLetters)-1 {
						m.flareLetterIdx++
					}
				case 2:
					if m.flareMagIdx < len(m.flareMagnitudes)-1 {
						m.flareMagIdx++
					}
				}
			case tea.MouseButtonLeft:
				if ok && msg.Action == tea.MouseActionRelease {
					m.flareFocus = col
					switch col {
					case 0:
						m.flareCompIdx = clampInt(row, 0, len(m.flareCompOptions)-1)
					case 1:
						m.flareLetterIdx = clampInt(row, 0, len(m.flareClassLetters)-1)
					case 2:
						m.flareMagIdx = clampInt(row, 0, len(m.flareMagnitudes)-1)
					}
				}
			}
		} else if m.mode == modeSelectFlares {
			switch msg.Button {
			case tea.MouseButtonWheelUp:
				if m.flareCursor > 0 {
					m.flareCursor--
					m.ensureFlareVisible()
				}
			case tea.MouseButtonWheelDown:
				if m.flareCursor < len(m.flareList)-1 {
					m.flareCursor++
					m.ensureFlareVisible()
				}
			case tea.MouseButtonLeft:
				if msg.Action == tea.MouseActionRelease {
					if m.flareCursor >= 0 && m.flareCursor < len(m.flareList) {
						m.flareSelected[m.flareCursor] = !m.flareSelected[m.flareCursor]
					}
				}
			}
			return m, nil
		}
		return m, cmd
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

	// Dedicated full-screen cache view (hide logo/summary)
	if m.mode == modeCacheView {
		body := renderCacheView(m, m.width)
		status := renderStatus(m.width)
		if m.height > 0 {
			gap := maxInt(m.height-lipgloss.Height(body)-lipgloss.Height(status), 0)
			return body + strings.Repeat("\n", gap) + status
		}
		return body + "\n" + status
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
		if nl := m.noticeLine(w); nl != "" {
			extraNotice = "\n" + "  " + nl
		}
	} else if m.mode == modeDateRange {
		body = summary + renderDateEditor(m, w)
		if nl := m.noticeLine(w); nl != "" {
			extraNotice = "\n" + "  " + nl
		}
	} else if m.mode == modeFlare {
		body = summary + renderFlareEditor(m, w)
		if nl := m.noticeLine(w); nl != "" {
			extraNotice = "\n" + "  " + nl
		}
	} else if m.mode == modeSelectFlares {
		body = summary + renderSelectFlares(m, w)
		if nl := m.noticeLine(w); nl != "" {
			extraNotice = "\n" + "  " + nl
		}
	} else if m.mode == modeCacheView {
		body = renderCacheView(m, w)
		if nl := m.noticeLine(w); nl != "" {
			extraNotice = "\n" + "  " + nl
		}
	} else if m.mode == modeCacheDelete {
		// hide summary; show centered delete table
		body = renderCacheDelete(m, w)
		if nl := m.noticeLine(w); nl != "" {
			extraNotice = "\n" + "  " + nl
		}
	} else {
		if m.cacheMenuOpen {
			body = summary + renderMenuWithCache(m, w)
		} else {
			body = summary + renderMenu(m, w)
		}
	}

	status := renderStatus(w)
	if m.height > 0 {
		contentHeight := lipgloss.Height(box) + 1 + lipgloss.Height(body+extraNotice)
		gap := maxInt(m.height-contentHeight-lipgloss.Height(status), 0)
		return box + "\n" + versionLine + body + extraNotice + strings.Repeat("\n", gap) + status
	}

	return box + "\n" + versionLine + body + extraNotice + "\n" + status
}

// flareHit identifies which column (0 comparator, 1 class, 2 magnitude) and which row is at x,y.
// x,y are 0-based terminal coordinates.
func (m model) flareHit(x, y int) (col int, row int, ok bool) {
	if m.mode != modeFlare || x < 0 || y < 0 {
		return 0, 0, false
	}

	cols := renderFlareColumns(m)
	if len(cols) != 3 {
		return 0, 0, false
	}

	// Logo block height
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

	// Build flare block components to measure positions.
	columns := lipgloss.JoinHorizontal(lipgloss.Top, cols...)
	title := summaryHeaderStyle.Copy().Bold(false).Render("Set Flare Filters")
	colWidth := lipgloss.Width(columns)
	if colWidth < lipgloss.Width(title) {
		colWidth = lipgloss.Width(title)
	}
	divWidth := maxInt(colWidth, lipgloss.Width(title)+6)
	divider := lipgloss.NewStyle().Foreground(lipgloss.Color("#3A3A3A")).Render(strings.Repeat("─", divWidth))
	titleBlock := lipgloss.JoinVertical(lipgloss.Center, title, divider)
	titleBlock = lipgloss.PlaceHorizontal(colWidth, lipgloss.Center, titleBlock)

	block := lipgloss.JoinVertical(lipgloss.Left, titleBlock, "", columns)

	blockWidth := lipgloss.Width(block)
	blockHeight := lipgloss.Height(block)

	// Positioning: View returns box + "\n" + versionLine + summary + renderFlareEditor (which starts with two newlines)
	header := box + "\n" + versionLine + summary
	topY := lipgloss.Height(header) + 2 /*leading newlines in editor*/

	if y < topY || y > topY+blockHeight {
		return 0, 0, false
	}

	offsetX := 0
	if w > blockWidth {
		offsetX = (w - blockWidth) / 2
	}
	if offsetX > 2 {
		offsetX -= 2
	}

	relY := y - topY
	relX := x - offsetX
	if relX < 0 {
		return 0, 0, false
	}

	titleHeight := lipgloss.Height(titleBlock) + 1 // includes blank line
	if relY < titleHeight {
		return 0, 0, false
	}
	optY := relY - titleHeight
	col0 := cols[0]
	col1 := cols[1]
	col2 := cols[2]
	pad := 2
	colStartX := []int{0, lipgloss.Width(col0) + pad, lipgloss.Width(col0) + pad + lipgloss.Width(col1) + pad}
	colWidths := []int{lipgloss.Width(col0), lipgloss.Width(col1), lipgloss.Width(col2)}
	colIdx := -1
	for i := 0; i < 3; i++ {
		if relX >= colStartX[i] && relX < colStartX[i]+colWidths[i] {
			colIdx = i
			break
		}
	}
	if colIdx == -1 {
		return 0, 0, false
	}

	// Each column layout: header, blank, options...
	if optY < 2 {
		return 0, 0, false
	}
	rowIdx := optY - 2

	var start, window, maxRows int
	switch colIdx {
	case 0:
		window = len(m.flareCompOptions)
		if len(m.flareCompOptions) > window {
			window = len(m.flareCompOptions)
		}
		start = 0
		maxRows = len(m.flareCompOptions)
	case 1:
		window = len(m.flareClassLetters)
		start = 0
		maxRows = len(m.flareClassLetters)
	case 2:
		window = 9
		maxRows = len(m.flareMagnitudes)
		if maxRows < window {
			window = maxRows
		}
		if maxRows > window {
			start = clampInt(m.flareMagIdx-window/2, 0, maxRows-window)
		}
	default:
		return 0, 0, false
	}

	if rowIdx < 0 || rowIdx >= window {
		return 0, 0, false
	}

	actualIdx := start + rowIdx
	if actualIdx >= maxRows {
		return 0, 0, false
	}

	return colIdx, actualIdx, true
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

func cacheFilePath() string {
	return filepath.Join("..", "flare_cache.tsv")
}

func loadCache() (string, []cacheRow, error) {
	path := cacheFilePath()
	data, err := os.ReadFile(path)
	if err != nil {
		return "", nil, err
	}
	lines := strings.Split(strings.TrimRight(string(data), "\n"), "\n")
	if len(lines) == 0 {
		return "", nil, fmt.Errorf("cache empty")
	}
	header := lines[0]
	var rows []cacheRow
	for _, line := range lines[1:] {
		if strings.TrimSpace(line) == "" {
			continue
		}
		fields := strings.Split(line, "\t")
		// description, flare_class, start, end, coordinates, wavelength
		row := cacheRow{full: line}
		if len(fields) > 0 {
			row.desc = fields[0]
		}
		if len(fields) > 1 {
			row.class = fields[1]
		}
		if len(fields) > 2 {
			row.start = fields[2]
		}
		if len(fields) > 3 {
			row.end = fields[3]
		}
		if len(fields) > 4 {
			row.coord = fields[4]
		}
		if len(fields) > 5 {
			row.wave = fields[5]
		}
		rows = append(rows, row)
	}
	return header, rows, nil
}

func truncateCell(s string, max int) string {
	if max <= 0 {
		return ""
	}
	runes := []rune(s)
	if len(runes) <= max {
		return s
	}
	return string(runes[:max])
}

// formatCacheTable builds a boxed table string for the cache rows.
func formatCacheTable(header string, rows []cacheRow) string {
	cols := []string{"DESC", "CLASS", "START", "END", "COORD", "WAVE"}
	widths := make([]int, len(cols))
	for i, c := range cols {
		widths[i] = lipgloss.Width(c)
	}
	maxWidths := []int{3, 8, 20, 20, 30, 8}
	for _, r := range rows {
		widths[0] = maxInt(widths[0], minInt(maxWidths[0], lipgloss.Width(r.desc)))
		widths[1] = maxInt(widths[1], minInt(maxWidths[1], lipgloss.Width(r.class)))
		widths[2] = maxInt(widths[2], minInt(maxWidths[2], lipgloss.Width(r.start)))
		widths[3] = maxInt(widths[3], minInt(maxWidths[3], lipgloss.Width(r.end)))
		widths[4] = maxInt(widths[4], minInt(maxWidths[4], lipgloss.Width(r.coord)))
		widths[5] = maxInt(widths[5], minInt(maxWidths[5], lipgloss.Width(r.wave)))
	}

	border := func(left, mid, right string) string {
		var parts []string
		for i, w := range widths {
			parts = append(parts, strings.Repeat("─", w+2))
			if i < len(widths)-1 {
				parts = append(parts, mid)
			}
		}
		return left + strings.Join(parts, "") + right
	}

	var b strings.Builder
	fmt.Fprintln(&b, border("┌", "┬", "┐"))
	var headerCells []string
	for i, c := range cols {
		headerCells = append(headerCells, fmt.Sprintf(" %-*s ", widths[i], c))
	}
	fmt.Fprintln(&b, "│"+strings.Join(headerCells, "│")+"│")
	fmt.Fprintln(&b, border("├", "┼", "┤"))

	if len(rows) == 0 {
		empty := []string{
			fmt.Sprintf(" %-*s ", widths[0], "(no cached flares)"),
			fmt.Sprintf(" %-*s ", widths[1], ""),
			fmt.Sprintf(" %-*s ", widths[2], ""),
			fmt.Sprintf(" %-*s ", widths[3], ""),
			fmt.Sprintf(" %-*s ", widths[4], ""),
			fmt.Sprintf(" %-*s ", widths[5], ""),
		}
		fmt.Fprintln(&b, "│"+strings.Join(empty, "│")+"│")
		fmt.Fprint(&b, border("└", "┴", "┘"))
		return b.String()
	}

	for _, r := range rows {
		cells := []string{
			fmt.Sprintf(" %-*s ", widths[0], truncateCell("...", widths[0])),
			fmt.Sprintf(" %-*s ", widths[1], truncateCell(r.class, widths[1])),
			fmt.Sprintf(" %-*s ", widths[2], truncateCell(r.start, widths[2])),
			fmt.Sprintf(" %-*s ", widths[3], truncateCell(r.end, widths[3])),
			fmt.Sprintf(" %-*s ", widths[4], truncateCell(r.coord, widths[4])),
			fmt.Sprintf(" %-*s ", widths[5], truncateCell(r.wave, widths[5])),
		}
		fmt.Fprintln(&b, "│"+strings.Join(cells, "│")+"│")
	}
	fmt.Fprint(&b, border("└", "┴", "┘"))
	return b.String()
}

func cacheHeaderView(m model, width int) string {
	title := lipgloss.NewStyle().
		BorderStyle(lipgloss.RoundedBorder()).
		Padding(0, 1).
		Render("flare_cache.tsv")
	line := strings.Repeat("─", maxInt(0, m.cacheViewport.Width-lipgloss.Width(title)))
	return lipgloss.JoinHorizontal(lipgloss.Center, title, line)
}

func cacheFooterView(m model, width int) string {
	info := lipgloss.NewStyle().
		BorderStyle(lipgloss.RoundedBorder()).
		Padding(0, 1).
		Render(fmt.Sprintf("%3.0f%%", m.cacheViewport.ScrollPercent()*100))
	line := strings.Repeat("─", maxInt(0, m.cacheViewport.Width-lipgloss.Width(info)))
	return lipgloss.JoinHorizontal(lipgloss.Center, line, info)
}

// renderCacheTableString builds a styled table (similar to previous layout).
func renderCacheTableString(rows []cacheRow, width int) string {
	// Responsive caps based on available width.
	if width <= 0 {
		width = 80
	}
	rowCap, descCap := 4, 3
	classCap, startCap, endCap, coordCap, waveCap := 8, 32, 32, 30, 8
	if width > 0 {
		switch {
		case width < 70:
			classCap, startCap, endCap, coordCap, waveCap = 5, 12, 12, 9, 5
		case width < 90:
			classCap, startCap, endCap, coordCap, waveCap = 7, 18, 18, 14, 7
		case width < 110:
			classCap, startCap, endCap, coordCap, waveCap = 9, 22, 22, 18, 8
		}
	}
	maxWidths := []int{rowCap, descCap, classCap, startCap, endCap, coordCap, waveCap}
	base := lipgloss.NewStyle().Padding(0, 1)
	headerStyle := base.Foreground(lipgloss.Color("252")).Bold(true)
	rowEven := base.Foreground(lipgloss.Color("245"))
	rowOdd := base.Foreground(lipgloss.Color("241"))
	descStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("241"))

	t := lgtbl.New().
		Border(lipgloss.NormalBorder()).
		BorderStyle(lipgloss.NewStyle().Foreground(lipgloss.Color("238"))).
		Headers("ROW", "DESC", "CLASS", "START", "END", "COORD", "WAVE")

	for i, r := range rows {
		rowNum := truncateCell(fmt.Sprintf("%d", i+1), maxWidths[0])
		desc := descStyle.Render(truncateCell("...", maxWidths[1]))
		class := truncateCell(r.class, maxWidths[2])
		start := truncateCell(r.start, maxWidths[3])
		end := truncateCell(r.end, maxWidths[4])
		coord := truncateCell(r.coord, maxWidths[5])
		wave := truncateCell(r.wave, maxWidths[6])
		t = t.Row(rowNum, desc, class, start, end, coord, wave)
	}

	t = t.StyleFunc(func(row, col int) lipgloss.Style {
		if row == lgtbl.HeaderRow {
			return headerStyle
		}
		if row%2 == 0 {
			return rowEven
		}
		return rowOdd
	})

	return t.String()
}

func clearCacheFile() (string, error) {
	path := cacheFilePath()
	header := "description\tflare_class\tstart\tend\tcoordinates\twavelength"
	if data, err := os.ReadFile(path); err == nil {
		lines := strings.Split(strings.TrimRight(string(data), "\n"), "\n")
		if len(lines) > 0 && strings.TrimSpace(lines[0]) != "" {
			header = lines[0]
		}
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, []byte(header+"\n"), 0o600); err != nil {
		return "", err
	}
	if err := os.Rename(tmp, path); err != nil {
		return "", err
	}
	return header, nil
}

func saveCachePruned(header string, rows []cacheRow, delete map[int]bool) error {
	path := cacheFilePath()
	tmp := path + ".tmp"
	f, err := os.Create(tmp)
	if err != nil {
		return err
	}
	defer f.Close()

	fmt.Fprintln(f, header)
	for i, r := range rows {
		if delete[i] {
			continue
		}
		if strings.TrimSpace(r.full) == "" {
			continue
		}
		fmt.Fprintln(f, r.full)
	}
	if err := f.Close(); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// centerContent pads each line to center content within a target width.
func centerContent(content string, width int) string {
	if width <= 0 {
		return content
	}
	lines := strings.Split(content, "\n")
	for i, line := range lines {
		w := lipgloss.Width(line)
		if w >= width {
			continue
		}
		pad := (width - w) / 2
		lines[i] = strings.Repeat(" ", pad) + line
	}
	return strings.Join(lines, "\n")
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

func (m model) noticeLine(width int) string {
	if m.notice == "" {
		return ""
	}
	if m.noticeSet <= 0 {
		return ""
	}
	elapsed := m.frame - m.noticeSet
	const hold = 10
	const life = 19 // ~1.5s at 80ms
	if elapsed >= life {
		return ""
	}
	t := 0.0
	if elapsed > hold {
		t = clamp(float64(elapsed-hold)/float64(life-hold), 0, 1)
	}
	col := blendHex("#FF6B81", "#353533", t)
	text := lipgloss.NewStyle().Foreground(lipgloss.Color(col)).Render(m.notice)
	widthTarget := width
	if widthTarget <= 0 {
		widthTarget = lipgloss.Width(text)
	}
	return lipgloss.Place(widthTarget, 1, lipgloss.Center, lipgloss.Top, text)
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
		parts = append(parts, base.Copy().Foreground(lipgloss.Color(col.Hex())).Render(string(r)))
	}
	return strings.Join(parts, "")
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
	help := menuHelpStyle.Render("space toggle • ctrl+a toggle all • enter save • esc cancel")

	block := lipgloss.JoinVertical(lipgloss.Left,
		titleBlock,
		"",
		list,
	)
	indent := func(s string) string {
		return " " + strings.ReplaceAll(s, "\n", "\n ")
	}

	if width <= 0 {
		return "\n\n" + indent(block) + "\n\n\n\n\n" + indent(lipgloss.PlaceHorizontal(width, lipgloss.Center, help))
	}

	placed := lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	placed = indent(placed)
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	helpLine = indent(helpLine)
	return "\n\n" + placed + "\n\n\n\n\n" + helpLine
}

func renderDateEditor(m model, width int) string {
	valueStyle := summaryValueStyle.Copy()
	focusStyle := lipgloss.NewStyle().Background(lipgloss.Color("#2A262A"))
	headerStyle := menuHelpStyle.Copy()
	promptStyle := menuHelpStyle.Copy().Bold(true)
	ghostStyle := menuHelpStyle.Copy().Faint(true)

	renderField := func(header, val, placeholder string, focused bool) string {
		line := lipgloss.JoinHorizontal(lipgloss.Top, promptStyle.Render("> "), valueStyle.Render(val))
		if strings.TrimSpace(val) == "" {
			if placeholder == "" {
				placeholder = "YYYY-MM-DD"
			}
			line = lipgloss.JoinHorizontal(lipgloss.Top, promptStyle.Render("> "), ghostStyle.Render(placeholder))
		}
		if focused {
			return focusStyle.Render(line)
		}
		return line
	}

	startField := renderField(
		"Start date (YYYY-MM-DD) -- leave blank to remain same",
		strings.TrimSpace(m.dateStart),
		strings.TrimSpace(m.cfg.START),
		m.dateFocus == 0,
	)
	endField := renderField(
		"End date   (YYYY-MM-DD) -- leave blank to remain same",
		strings.TrimSpace(m.dateEnd),
		strings.TrimSpace(m.cfg.END),
		m.dateFocus == 1,
	)

	block := lipgloss.JoinVertical(lipgloss.Left,
		headerStyle.Render("Start date (YYYY-MM-DD) -- leave blank to remain same"),
		startField,
		"",
		"",
		headerStyle.Render("End date   (YYYY-MM-DD) -- leave blank to remain same"),
		endField,
	)

	help := menuHelpStyle.Render("tab switch • enter save • esc cancel")

	indent := func(s string) string {
		return " " + strings.ReplaceAll(s, "\n", "\n ")
	}

	if width <= 0 {
		helpLine := lipgloss.PlaceHorizontal(width, lipgloss.Center, help)
		combined := lipgloss.JoinVertical(lipgloss.Left, block, "", "", helpLine)
		return "\n\n" + indent(combined)
	}

	placed := lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	placed = indent(placed)
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	helpLine = indent(helpLine)
	combined := lipgloss.JoinVertical(lipgloss.Left, placed, "", "", helpLine)
	return "\n\n" + combined
}

func renderFlareColumns(m model) []string {
	headerStyle := menuHelpStyle.Copy()
	itemStyle := summaryValueStyle.Copy()
	checkStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1"))
	focusBox := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		Padding(0, 1)
	plainBox := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		Padding(0, 1)

	renderColumn := func(title string, opts []string, selected int, focused bool, window int) string {
		start := 0
		if len(opts) > window {
			start = clampInt(selected-window/2, 0, len(opts)-window)
		}
		end := minInt(len(opts), start+window)

		var rows []string
		for i := start; i < end; i++ {
			prefix := "[ ]"
			if i == selected {
				prefix = checkStyle.Render("[x]")
			}
			line := lipgloss.JoinHorizontal(lipgloss.Top, prefix, " ", itemStyle.Render(opts[i]))
			rows = append(rows, line)
		}

		headerText := headerStyle.Copy().Foreground(lipgloss.Color("#3A3A3A")).Render(title)
		if focused {
			headerAnimT := clamp(float64(maxInt(m.frame-m.flareFocusFrame, 0))/8.0, 0, 1)
			headerText = renderGradientText(
				title,
				blendHex("#7D5FFF", "#FFB7D5", headerAnimT),
				blendHex("#8B5EDB", "#F785D1", headerAnimT),
				headerStyle.Copy().Bold(true),
			)
		}

		content := lipgloss.JoinVertical(
			lipgloss.Left,
			headerText,
			"",
			strings.Join(rows, "\n"),
		)
		if focused {
			return focusBox.Copy().
				BorderForeground(lipgloss.Color("#F785D1")).
				Render(content)
		}
		return plainBox.Copy().
			BorderForeground(lipgloss.Color("#2B2B2B")).
			Render(content)
	}

	compCol := renderColumn("Comparator", m.flareCompOptions, m.flareCompIdx, m.flareFocus == 0, len(m.flareCompOptions))
	letCol := renderColumn("GOES Class", m.flareClassLetters, m.flareLetterIdx, m.flareFocus == 1, len(m.flareClassLetters))
	magCol := renderColumn("Magnitude (Scroll)", m.flareMagnitudes, m.flareMagIdx, m.flareFocus == 2, 9)

	return []string{
		lipgloss.NewStyle().PaddingRight(2).Render(compCol),
		lipgloss.NewStyle().PaddingRight(2).Render(letCol),
		magCol,
	}
}

func flareTableWidths(m model) (int, int, int, int, int) {
	wSel := lipgloss.Width("SEL")
	if wSel < lipgloss.Width("[x]") {
		wSel = lipgloss.Width("[x]")
	}
	wClass := lipgloss.Width("Class")
	wStart := lipgloss.Width("Start")
	wEnd := lipgloss.Width("End")
	wCoord := lipgloss.Width("Coordinates")
	for _, e := range m.flareList {
		if w := lipgloss.Width(e.class); w > wClass {
			wClass = w
		}
		if w := lipgloss.Width(e.start); w > wStart {
			wStart = w
		}
		if w := lipgloss.Width(e.end); w > wEnd {
			wEnd = w
		}
		if w := lipgloss.Width(e.coord); w > wCoord {
			wCoord = w
		}
	}
	pad := 2
	return wSel + pad, wClass + pad, wStart + pad, wEnd + pad, wCoord + pad
}

func flareTableHeader(m model) (string, string) {
	wSel, wClass, wStart, wEnd, wCoord := flareTableWidths(m)
	format := fmt.Sprintf("│ %%-%ds │ %%-%ds │ %%-%ds │ %%-%ds │ %%-%ds │", wSel, wClass, wStart, wEnd, wCoord)
	header := fmt.Sprintf(format, "SEL", "CLASS", "START", "END", "COORDINATES")
	return header, strings.Repeat("─", lipgloss.Width(header))
}

func flareTableRows(m model, start, end int) ([]string, int) {
	wSel, wClass, wStart, wEnd, wCoord := flareTableWidths(m)
	format := fmt.Sprintf("│ %%-%ds │ %%-%ds │ %%-%ds │ %%-%ds │ %%-%ds │", wSel, wClass, wStart, wEnd, wCoord)
	var rows []string
	maxW := 0
	for i := start; i < end; i++ {
		entry := m.flareList[i]
		check := "[ ]"
		if m.flareSelected[i] {
			check = lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1")).Render("[x]")
		}
		line := fmt.Sprintf(format, check, entry.class, entry.start, entry.end, entry.coord)
		style := lipgloss.NewStyle().Foreground(lipgloss.Color("245"))
		if (i-start)%2 == 1 {
			style = lipgloss.NewStyle().Foreground(lipgloss.Color("252"))
		}
		rendered := style.Render(line)
		rows = append(rows, rendered)
		if w := lipgloss.Width(rendered); w > maxW {
			maxW = w
		}
	}
	if len(rows) == 0 {
		return rows, maxW
	}
	return rows, maxW
}

func renderFlareEditor(m model, width int) string {
	titleStyle := summaryHeaderStyle.Copy().Bold(false)
	cols := renderFlareColumns(m)
	columns := lipgloss.JoinHorizontal(lipgloss.Top, cols...)
	title := titleStyle.Render("Set Flare Filters")
	colWidth := lipgloss.Width(columns)
	if colWidth < lipgloss.Width(title) {
		colWidth = lipgloss.Width(title)
	}
	divWidth := maxInt(colWidth, lipgloss.Width(title)+6)
	divider := lipgloss.NewStyle().Foreground(lipgloss.Color("#3A3A3A")).Render(strings.Repeat("─", divWidth))
	titleBlock := lipgloss.JoinVertical(lipgloss.Center, title, divider)
	titleBlock = lipgloss.PlaceHorizontal(colWidth, lipgloss.Center, titleBlock)

	block := lipgloss.JoinVertical(lipgloss.Left, titleBlock, "", columns)

	help := menuHelpStyle.Render("←/→/tab switch • ↑/↓ select • enter save • esc cancel")

	if width <= 0 {
		return "\n\n" + block + "\n\n" + help
	}

	placed := lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	return "\n\n" + placed + "\n\n" + helpLine
}

func renderSelectFlares(m model, width int) string {
	title := summaryHeaderStyle.Copy().Bold(false).Render("Choose Flares to Catalogue (Scroll)")

	if m.flareLoading {
		spin := ""
		if len(m.spinFrames) > 0 {
			spin = m.spinFrames[m.spinIndex]
		}
		msg := menuHelpStyle.Render(fmt.Sprintf("Loading flares %s", spin))
		block := lipgloss.JoinVertical(lipgloss.Center, "", msg)
		if width <= 0 {
			return "\n" + block
		}
		return "\n" + lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	}

	if m.flareLoadError != "" {
		msg := lipgloss.NewStyle().Foreground(lipgloss.Color("#FF6B81")).Render(m.flareLoadError)
		block := lipgloss.JoinVertical(lipgloss.Center, title, "", msg)
		if width <= 0 {
			return "\n\n" + block
		}
		return "\n\n" + lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	}

	if len(m.flareList) == 0 {
		msg := menuHelpStyle.Render("No flares found.")
		block := lipgloss.JoinVertical(lipgloss.Center, title, "", msg)
		if width <= 0 {
			return "\n\n" + block
		}
		return "\n\n" + lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	}

	height := flareViewHeight(m)
	if m.flareOffset < 0 {
		m.flareOffset = 0
	}
	if height == 0 {
		msg := menuHelpStyle.Render("No flares found.")
		block := lipgloss.JoinVertical(lipgloss.Center, title, "", msg)
		if width <= 0 {
			return "\n\n" + block
		}
		return "\n\n" + lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	}
	tableStr := renderSelectFlaresTable(m, width, height)
	titleLine := title
	if width > 0 {
		titleLine = lipgloss.Place(width, lipgloss.Height(title), lipgloss.Center, lipgloss.Top, title)
	} else {
		titleLine = lipgloss.Place(lipgloss.Width(tableStr), lipgloss.Height(title), lipgloss.Center, lipgloss.Top, title)
	}
	body := lipgloss.JoinVertical(lipgloss.Left, titleLine, "", tableStr)
	help := menuHelpStyle.Render("↑/↓ move • space toggle • enter save • esc cancel")

	if width <= 0 {
		return "\n\n" + body + "\n\n" + help
	}

	placed := lipgloss.Place(width, lipgloss.Height(body), lipgloss.Center, lipgloss.Top, body)
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	return "\n\n" + placed + "\n\n" + helpLine
}

func renderCacheView(m model, width int) string {
	// Always rebuild content so columns/values stay in sync with current cache.
	availWidth := width
	if availWidth > 0 {
		availWidth = maxInt(availWidth-6, 20) // leave room for borders/padding
	}
	m.cacheContent = renderCacheTableString(m.cacheRows, availWidth)
	contentWidth := lipgloss.Width(m.cacheContent)
	contentHeight := lipgloss.Height(m.cacheContent)
	targetW := minInt(maxInt(contentWidth+2, 20), maxInt(availWidth-2, 20))
	targetH := minInt(contentHeight+2, maxInt(m.height-10, 5))
	m.cacheViewport.Width = targetW
	m.cacheViewport.Height = targetH
	centered := centerContent(m.cacheContent, m.cacheViewport.Width)
	m.cacheViewport.SetContent(centered)

	header := cacheHeaderView(m, width)
	footer := cacheFooterView(m, width)
	help := menuHelpStyle.Render("↑/↓ scroll • pgup/pgdown jump • del delete • q/esc back")

	box := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("#8B5EDB")).
		Padding(0, 1).
		Width(m.cacheViewport.Width + 2)

	centeredView := lipgloss.Place(
		m.cacheViewport.Width,
		lipgloss.Height(m.cacheViewport.View()),
		lipgloss.Center,
		lipgloss.Top,
		m.cacheViewport.View(),
	)

	mainBlock := box.Render(centeredView)

	body := lipgloss.JoinVertical(
		lipgloss.Center,
		header,
		mainBlock,
		footer,
		"",
		help,
	)
	if width <= 0 {
		return "\n\n" + body
	}
	placed := lipgloss.Place(width, lipgloss.Height(body), lipgloss.Center, lipgloss.Top, body)
	// small top padding
	return "\n\n" + placed
}

func renderCacheDelete(m model, width int) string {
	title := summaryHeaderStyle.Copy().Bold(false).Render("Delete Cache Rows (Scroll)")
	height := cacheViewHeight(m)
	if len(m.cacheRows) == 0 {
		msg := menuHelpStyle.Render("Cache empty.")
		block := lipgloss.JoinVertical(lipgloss.Center, title, "", msg)
		bw := lipgloss.Width(block)
		effW := width
		if effW <= 0 {
			effW = bw
		}
		if bw > effW {
			effW = bw
		}
		return "\n\n" + lipgloss.Place(effW, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	}

	start := clampInt(m.cacheOffset, 0, maxInt(len(m.cacheRows)-height, 0))
	end := minInt(len(m.cacheRows), start+height)

	base := lipgloss.NewStyle().Padding(0, 1)
	headerStyle := base.Foreground(lipgloss.Color("252")).Bold(true)
	rowEven := base.Foreground(lipgloss.Color("245"))
	rowOdd := base.Foreground(lipgloss.Color("252"))
	cursorStyle := base.Foreground(lipgloss.Color("#F785D1")).Background(lipgloss.Color("#2A262A"))
	selMark := lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1"))

	trunc := func(s string, max int) string {
		if max <= 0 {
			return ""
		}
		if len(s) <= max {
			return s
		}
		if max <= 3 {
			return s[:max]
		}
		return s[:max-3] + "..."
	}

	// Responsive column caps based on available width.
	maxClass, maxStart, maxEnd, maxCoord, maxWave := 12, 26, 26, 22, 10
	if width > 0 {
		switch {
		case width < 70:
			maxClass, maxStart, maxEnd, maxCoord, maxWave = 4, 10, 10, 8, 4
		case width < 90:
			maxClass, maxStart, maxEnd, maxCoord, maxWave = 6, 14, 14, 10, 6
		case width < 110:
			maxClass, maxStart, maxEnd, maxCoord, maxWave = 8, 18, 18, 14, 8
		}
	}

	rows := make([][]string, 0, end-start)
	for i := start; i < end; i++ {
		r := m.cacheRows[i]
		sel := "[ ]"
		if m.cachePick[i] {
			sel = selMark.Render("[x]")
		}
		desc := "..."
		rows = append(rows, []string{
			sel,
			desc,
			trunc(r.class, maxClass),
			trunc(r.start, maxStart),
			trunc(r.end, maxEnd),
			trunc(r.coord, maxCoord),
			trunc(r.wave, maxWave),
		})
	}

	t := lgtbl.New().
		Border(lipgloss.NormalBorder()).
		BorderStyle(lipgloss.NewStyle().Foreground(lipgloss.Color("238"))).
		Headers("SEL", "DESC", "CLASS", "START", "END", "COORD", "WAVE").
		Rows(rows...).
		StyleFunc(func(row, col int) lipgloss.Style {
			if row == lgtbl.HeaderRow {
				return headerStyle
			}
			abs := start + row
			if abs == m.cacheCursor {
				return cursorStyle
			}
			if abs%2 == 0 {
				return rowEven
			}
			return rowOdd
		})

	tableStr := t.String()
	help := menuHelpStyle.Render("↑/↓ move • space toggle • enter delete • q/esc cancel")
	innerW := lipgloss.Width(tableStr)
	if w := lipgloss.Width(title); w > innerW {
		innerW = w
	}
	if w := lipgloss.Width(help); w > innerW {
		innerW = w
	}
	if innerW == 0 {
		innerW = width
	}
	titleLine := lipgloss.Place(innerW, lipgloss.Height(title), lipgloss.Center, lipgloss.Top, title)
	tableBlock := lipgloss.Place(innerW, lipgloss.Height(tableStr), lipgloss.Center, lipgloss.Top, tableStr)
	helpLine := lipgloss.Place(innerW, 1, lipgloss.Center, lipgloss.Top, help)

	body := lipgloss.JoinVertical(lipgloss.Center, titleLine, "", tableBlock, "", helpLine)
	effW := width
	if effW <= 0 {
		effW = innerW
	}
	if innerW > effW {
		effW = innerW
	}
	return "\n\n" + lipgloss.Place(effW, lipgloss.Height(body), lipgloss.Center, lipgloss.Top, body)
}

// renderSelectFlaresTable builds the flare selection table with distinct columns and a selectable SEL column.
func renderSelectFlaresTable(m model, width int, height int) string {
	start := clampInt(m.flareOffset, 0, maxInt(len(m.flareList)-height, 0))
	end := minInt(len(m.flareList), start+height)

	base := lipgloss.NewStyle().Padding(0, 1)
	headerStyle := base.Foreground(lipgloss.Color("252")).Bold(true)
	cursorStyle := base.Foreground(lipgloss.Color("#F785D1")).Background(lipgloss.Color("#2A262A"))
	selectColStyle := base.Foreground(lipgloss.Color("#C7CDD6")) // subtle accent for SEL
	classEvenStyle := base.Foreground(lipgloss.Color("245"))     // lighter pattern (was start/end)
	classOddStyle := base.Foreground(lipgloss.Color("252"))
	coordEvenStyle := base.Foreground(lipgloss.Color("#B8C3D9")) // soft gray-blue
	coordOddStyle := base.Foreground(lipgloss.Color("#A0A9BE"))  // slightly deeper gray-blue
	startEndEvenStyle := base.Foreground(lipgloss.Color("241"))  // more subdued (was class)
	startEndOddStyle := base.Foreground(lipgloss.Color("245"))
	evenStyle := base.Foreground(lipgloss.Color("245"))
	oddStyle := base.Foreground(lipgloss.Color("252"))
	selMark := lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1"))

	rows := make([][]string, 0, end-start)
	for i := start; i < end; i++ {
		entry := m.flareList[i]
		sel := "[ ]"
		if m.flareSelected[i] {
			sel = selMark.Render("[x]")
		}
		rows = append(rows, []string{
			sel,
			entry.class,
			entry.start,
			entry.end,
			entry.coord,
		})
	}

	t := lgtbl.New().
		Border(lipgloss.NormalBorder()).
		BorderStyle(lipgloss.NewStyle().Foreground(lipgloss.Color("238"))).
		Headers("SEL", "CLASS", "START", "END", "COORDINATES").
		Rows(rows...).
		StyleFunc(func(row, col int) lipgloss.Style {
			if row == lgtbl.HeaderRow {
				return headerStyle
			}
			abs := start + row
			if abs == m.flareCursor {
				return cursorStyle
			}
			if col == 0 {
				return selectColStyle
			}
			evenRow := abs%2 == 0
			switch col {
			case 1:
				if evenRow {
					return classEvenStyle
				}
				return classOddStyle
			case 2, 3:
				if evenRow {
					return startEndEvenStyle
				}
				return startEndOddStyle
			case 4:
				if evenRow {
					return coordEvenStyle
				}
				return coordOddStyle
			}
			if abs%2 == 0 {
				return evenStyle
			}
			return oddStyle
		})

	tableStr := t.String()
	if width > 0 {
		tableStr = lipgloss.Place(width, lipgloss.Height(tableStr), lipgloss.Center, lipgloss.Top, tableStr)
	}
	return tableStr
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

	menuBlock := strings.Join(lines, "\n")

	noticeLine := ""
	if nl := m.noticeLine(width); nl != "" {
		noticeLine = nl
	}

	helpText := "↑/k up • ↓/j down • enter submit"

	if width <= 0 {
		help := menuHelpStyle.Render(helpText)
		if noticeLine != "" {
			return "\n\n" + menuBlock + "\n\n" + "  " + noticeLine + "\n\n" + help
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
		noticeLine = "  " + noticeLine
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

// renderMenuWithCache shows the main menu with an inline submenu under Cache Options.
func renderMenuWithCache(m model, width int) string {
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

		// Inline submenu under Cache Options
		if item == "Cache Options" && m.cacheMenuOpen {
			maxCache := 0
			for _, it := range m.cacheMenuItems {
				if w := lipgloss.Width(it); w > maxCache {
					maxCache = w
				}
			}
			innerWidth := maxCache + 4 // cursor + padding
			targetHeight := len(m.cacheMenuItems) + 2
			delta := m.frame - m.cacheOpenFrame
			if delta < 0 {
				delta = 0
			}
			heightAnim := minInt(targetHeight, (delta+1)*3) // faster grow
			if heightAnim < 1 {
				heightAnim = 1
			}

			progress := float64(delta) / float64(targetHeight)
			if progress > 1 {
				progress = 1
			}
			col := blendHex("#7D5FFF", "#F785D1", progress)
			if heightAnim >= targetHeight {
				col = "#8B5EDB" // settle to static purple when fully open
			}
			boxStyle := lipgloss.NewStyle().Foreground(lipgloss.Color(col))

			if heightAnim >= targetHeight {
				var sub []string
				top := boxStyle.Render("   ╭" + strings.Repeat("─", innerWidth) + "╮")
				sub = append(sub, top)
				for j, subItem := range m.cacheMenuItems {
					sStyle := menuItemStyle.Copy().Foreground(lipgloss.Color("252"))
					sCursor := "  "
					if j == m.cacheSelected {
						sStyle = menuSelectedStyle
						sCursor = lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1")).Render("» ")
					}
					sLine := sCursor + sStyle.Render(subItem)
					padded := sLine
					if pad := innerWidth - lipgloss.Width(sLine); pad > 0 {
						padded += strings.Repeat(" ", pad)
					}
					leftBar := boxStyle.Render("   │")
					rightBar := boxStyle.Render("│")
					sub = append(sub, leftBar+padded+rightBar)
				}
				bottom := boxStyle.Render("   ╰" + strings.Repeat("─", innerWidth) + "╯")
				sub = append(sub, bottom)
				lines = append(lines, strings.Join(sub, "\n"))
			} else {
				var partial []string
				partial = append(partial, boxStyle.Render("   ╭"+strings.Repeat("─", innerWidth)+"╮"))
				mid := heightAnim - 1
				if mid < 0 {
					mid = 0
				}
				for k := 0; k < mid; k++ {
					leftBar := boxStyle.Render("   │")
					rightBar := boxStyle.Render("│")
					partial = append(partial, leftBar+strings.Repeat(" ", innerWidth)+rightBar)
				}
				lines = append(lines, strings.Join(partial, "\n"))
			}
		}
	}

	mainBlock := strings.Join(lines, "\n")

	noticeLine := ""
	if nl := m.noticeLine(width); nl != "" {
		noticeLine = nl
	}

	helpText := "↑/k up • ↓/j down • enter submit • esc close cache"
	help := menuHelpStyle.Render(helpText)
	joined := mainBlock

	if width <= 0 {
		block := "\n\n" + joined
		if noticeLine != "" {
			block += "\n\n" + noticeLine
		}
		return block + "\n\n" + help
	}

	placed := lipgloss.Place(width, lipgloss.Height(joined), lipgloss.Center, lipgloss.Top, joined)
	if noticeLine != "" {
		if strings.HasPrefix(noticeLine, " ") {
			noticeLine = noticeLine[1:]
		}
		if strings.HasPrefix(noticeLine, " ") {
			noticeLine = noticeLine[1:]
		}
		noticeLine = "  " + noticeLine
	}
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	block := "\n\n" + placed
	if noticeLine != "" {
		block += "\n\n" + noticeLine
	}
	return block + "\n\n" + helpLine
}

// cacheMenuIndexAt maps mouse coords to a cache submenu item when open.
func (m model) cacheMenuIndexAt(x, y int) (int, bool) {
	if !m.cacheMenuOpen || m.mode != modeMain {
		return 0, false
	}

	// Header height (logo + version + summary)
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
	header := box + "\n" + versionLine + summary
	menuTop := maxInt(lipgloss.Height(header)+1, 0) // slight downward shift to align with cursor

	// Build menu lines with expanded cache submenu (structural only).
	var lines []string
	maxText := 0
	for _, item := range m.menuItems {
		if val := lipgloss.Width(item); val > maxText {
			maxText = val
		}
	}

	cacheOptLine := -1
	for _, item := range m.menuItems {
		cursor := "  "
		cursorW := lipgloss.Width(cursor)
		lineContent := cursor + menuItemStyle.Render(item)
		line := lipgloss.PlaceHorizontal(maxText+cursorW, lipgloss.Center, lineContent)
		lines = append(lines, line)
		if item == "Cache Options" {
			cacheOptLine = len(lines) - 1
			maxCache := 0
			for _, it := range m.cacheMenuItems {
				if w := lipgloss.Width(it); w > maxCache {
					maxCache = w
				}
			}
			innerWidth := maxCache + 4
			lines = append(lines, "   ╭"+strings.Repeat("─", innerWidth)+"╮")
			for _, subItem := range m.cacheMenuItems {
				sLine := "  " + menuItemStyle.Render(subItem)
				if pad := innerWidth - lipgloss.Width(sLine); pad > 0 {
					sLine += strings.Repeat(" ", pad)
				}
				lines = append(lines, "   │"+sLine+"│")
			}
			lines = append(lines, "   ╰"+strings.Repeat("─", innerWidth)+"╯")
		}
	}

	if cacheOptLine == -1 {
		return 0, false
	}

	menuHeight := len(lines)
	if y < menuTop || y >= menuTop+menuHeight {
		return 0, false
	}

	relativeY := y - menuTop
	subStart := cacheOptLine + 1 // top border
	itemStart := subStart + 1    // first item
	if relativeY < itemStart || relativeY >= itemStart+len(m.cacheMenuItems) {
		return 0, false
	}
	idx := relativeY - itemStart
	if idx < 0 || idx >= len(m.cacheMenuItems) {
		return 0, false
	}
	return idx, true
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
		{"Comparator", prettyComparator(cfg.COMPARATOR)},
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

func prettyComparator(val string) string {
	val = strings.TrimSpace(val)
	if val == "" {
		return "<unset>"
	}
	switch val {
	case ">=":
		return "≥"
	case "<=":
		return "≤"
	default:
		return val
	}
}

func comparatorASCII(val string) string {
	val = strings.TrimSpace(val)
	switch val {
	case "≥":
		return ">="
	case "≤":
		return "<="
	case "All", "ALL":
		return "All"
	default:
		return val
	}
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

func defaultComparatorOptions() ([]string, map[string]string) {
	opts := []string{">", "≥", "==", "≤", "<", "All"}
	m := map[string]string{
		">":   ">",
		"≥":   ">=",
		"==":  "==",
		"≤":   "<=",
		"<":   "<",
		"All": "All",
	}
	return opts, m
}

func defaultClassLetters() []string {
	return []string{"A", "B", "C", "M", "X"}
}

func defaultMagnitudes() []string {
	var mags []string
	for i := 0; i <= 9; i++ {
		for t := 0; t <= 9; t++ {
			mags = append(mags, fmt.Sprintf("%d.%d", i, t))
		}
	}
	return mags
}

func parseFlareSelection(cfg config, compOpts []string, compMap map[string]string, letters, mags []string) (int, int, int) {
	compIdx := 0
	letterIdx := 0
	magIdx := 0

	currentComp := strings.TrimSpace(cfg.COMPARATOR)
	currentClass := strings.TrimSpace(cfg.FLARE_CLASS)

	// comparator
	if currentComp != "" {
		for i, opt := range compOpts {
			val := compMap[opt]
			if val == "" {
				val = opt
			}
			if val == currentComp {
				compIdx = i
				break
			}
		}
	}

	// class
	if len(currentClass) >= 1 {
		letter := string(currentClass[0])
		for i, l := range letters {
			if l == letter {
				letterIdx = i
				break
			}
		}
		if len(currentClass) > 1 {
			mag := currentClass[1:]
			for i, m := range mags {
				if m == mag {
					magIdx = i
					break
				}
			}
		}
	}

	return compIdx, letterIdx, magIdx
}

func loadFlaresCmd(cfg config) tea.Cmd {
	return func() tea.Msg {
		cmp := comparatorASCII(cfg.COMPARATOR)
		if strings.TrimSpace(cfg.START) == "" || strings.TrimSpace(cfg.END) == "" || strings.TrimSpace(cfg.WAVE) == "" || cmp == "" {
			return flaresLoadedMsg{err: fmt.Errorf("missing required fields")}
		}

		flareClass := cfg.FLARE_CLASS
		if strings.TrimSpace(flareClass) == "" {
			flareClass = "A0.0"
		}

		tmp, err := os.CreateTemp("", "pocky_flares_*.tsv")
		if err != nil {
			return flaresLoadedMsg{err: err}
		}
		tmp.Close()
		tmpPath := tmp.Name()
		defer os.Remove(tmpPath)

		cmd := exec.Command("python", "query.py", cfg.START, cfg.END, cmp, flareClass, cfg.WAVE, tmpPath)
		cmd.Dir = ".."
		if output, err := cmd.CombinedOutput(); err != nil {
			return flaresLoadedMsg{err: fmt.Errorf("flare listing failed: %v (%s)", err, strings.TrimSpace(string(output)))}
		}

		f, err := os.Open(tmpPath)
		if err != nil {
			return flaresLoadedMsg{err: err}
		}
		defer f.Close()

		scanner := bufio.NewScanner(f)
		if !scanner.Scan() {
			return flaresLoadedMsg{err: fmt.Errorf("empty flare listing")}
		}
		header := scanner.Text()
		var entries []flareEntry
		for scanner.Scan() {
			line := scanner.Text()
			fields := strings.Split(line, "\t")
			if len(fields) < 6 {
				continue
			}
			startHuman := isoToHuman(fields[2])
			endHuman := isoToHuman(fields[3])
			if endHuman == "" {
				endHuman = startHuman
			}
			entries = append(entries, flareEntry{
				desc:  fields[0],
				class: fields[1],
				start: startHuman,
				end:   endHuman,
				coord: fields[4],
				full:  line,
			})
		}
		if err := scanner.Err(); err != nil {
			return flaresLoadedMsg{err: err}
		}
		return flaresLoadedMsg{entries: entries, header: header}
	}
}

func saveFlareSelection(header string, entries []flareEntry, selected map[int]bool) error {
	if len(selected) == 0 {
		return nil
	}
	var chosen []string
	for idx := range selected {
		if idx >= 0 && idx < len(entries) {
			chosen = append(chosen, entries[idx].full)
		}
	}
	if len(chosen) == 0 {
		return nil
	}

	cachePath := filepath.Join("..", "flare_cache.tsv")
	existingHeader := header
	var existing []string
	if data, err := os.ReadFile(cachePath); err == nil {
		lines := strings.Split(strings.TrimRight(string(data), "\n"), "\n")
		if len(lines) > 0 {
			existingHeader = lines[0]
			if len(lines) > 1 {
				existing = lines[1:]
			}
		}
	}
	if strings.TrimSpace(existingHeader) == "" {
		existingHeader = "description\tflare_class\tstart\tend\tcoordinates\twavelength"
	}

	tmpPath := cachePath + ".tmp"
	out, err := os.Create(tmpPath)
	if err != nil {
		return err
	}
	defer out.Close()

	seen := make(map[string]struct{})
	writeLine := func(line string) {
		if _, ok := seen[line]; ok {
			return
		}
		seen[line] = struct{}{}
		fmt.Fprintln(out, line)
	}

	writeLine(existingHeader)
	for _, line := range existing {
		if strings.TrimSpace(line) != "" {
			writeLine(line)
		}
	}
	for _, line := range chosen {
		if strings.TrimSpace(line) != "" {
			writeLine(line)
		}
	}

	if err := out.Close(); err != nil {
		return err
	}
	return os.Rename(tmpPath, cachePath)
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

func minInt(a, b int) int {
	if a < b {
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

// ensureFlareVisible adjusts the offset so the cursor row remains within the viewport.
func (m *model) ensureFlareVisible() {
	h := flareViewHeight(*m)
	if h <= 0 {
		m.flareOffset = 0
		return
	}
	if m.flareCursor < 0 {
		m.flareCursor = 0
	}
	if m.flareCursor >= len(m.flareList) {
		m.flareCursor = len(m.flareList) - 1
	}
	if m.flareCursor < m.flareOffset {
		m.flareOffset = m.flareCursor
	}
	if m.flareCursor >= m.flareOffset+h {
		m.flareOffset = m.flareCursor - h + 1
	}
	maxOffset := maxInt(len(m.flareList)-h, 0)
	if m.flareOffset > maxOffset {
		m.flareOffset = maxOffset
	}
	if m.flareOffset < 0 {
		m.flareOffset = 0
	}
}

// ensureCacheVisible keeps the cache cursor within the viewport.
func (m *model) ensureCacheVisible() {
	h := cacheViewHeight(*m)
	if h <= 0 {
		m.cacheOffset = 0
		return
	}
	if m.cacheCursor < 0 {
		m.cacheCursor = 0
	}
	if m.cacheCursor >= len(m.cacheRows) {
		m.cacheCursor = len(m.cacheRows) - 1
	}
	if m.cacheCursor < m.cacheOffset {
		m.cacheOffset = m.cacheCursor
	}
	if m.cacheCursor >= m.cacheOffset+h {
		m.cacheOffset = m.cacheCursor - h + 1
	}
	maxOffset := maxInt(len(m.cacheRows)-h, 0)
	if m.cacheOffset > maxOffset {
		m.cacheOffset = maxOffset
	}
	if m.cacheOffset < 0 {
		m.cacheOffset = 0
	}
}

// renderProgress draws a simple horizontal progress bar.
func renderProgress(current, total, width int) string {
	if width < 10 {
		width = 10
	}
	if total <= 0 {
		total = 1
	}
	if current < 0 {
		current = 0
	}
	if current > total {
		current = total
	}
	percent := float64(current) / float64(total)
	fillCount := int(percent * float64(width))
	if fillCount > width {
		fillCount = width
	}
	filled := strings.Repeat("█", fillCount)
	empty := strings.Repeat("─", maxInt(width-fillCount, 0))
	label := fmt.Sprintf(" %3.0f%%", percent*100)
	bar := filled + empty
	if len(label) <= len(bar) {
		bar = bar[:len(bar)-len(label)] + label
	} else {
		bar += label
	}
	return menuHelpStyle.Render(bar)
}
