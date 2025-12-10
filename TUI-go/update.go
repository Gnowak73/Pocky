package main

import (
	"fmt"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

func tick() tea.Cmd {
	return tea.Tick(time.Millisecond*80, func(time.Time) tea.Msg { return tickMsg{} })
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
			m.cache.viewport.Width = maxInt(msg.Width-6, 20)
			m.cache.viewport.Height = maxInt(msg.Height-10, 8)
			if m.mode == modeCacheView && m.cache.content != "" {
				m.cache.viewport.SetContent(m.cache.content)
			}
		}
	case tickMsg:
		m.frame++
		m.logo.colored = colorizeLogo(m.logo.lines, m.logo.blockW, m.frame)
		if m.notice != "" && m.noticeSet > 0 && m.frame-m.noticeSet > 19 {
			m.notice = ""
		}
		if m.flareSelector.loading && len(m.spinner.frames) > 0 {
			m.spinner.index = (m.spinner.index + 1) % len(m.spinner.frames)
		}
		return m, tick()
	case flaresLoadedMsg:
		return m.handleFlaresLoaded(msg)
	case tea.KeyMsg:
		return m.handleKeyMsg(msg)
	case tea.MouseMsg:
		return m.handleMouseMsg(msg)
	}
	return m, nil
}

func (m model) handleFlaresLoaded(msg flaresLoadedMsg) (tea.Model, tea.Cmd) {
	m.flareSelector.loading = false
	if msg.err != nil {
		m.flareSelector.loadError = msg.err.Error()
		m.notice = m.flareSelector.loadError
		m.noticeSet = m.frame
		m.mode = modeMain
		return m, nil
	}
	m.flareSelector.list = msg.entries
	m.flareSelector.header = msg.header
	m.flareSelector.selected = make(map[int]bool)
	if len(m.flareSelector.list) == 0 {
		m.notice = "No flares found."
		m.noticeSet = m.frame
		m.mode = modeMain
		return m, nil
	}
	m.flareSelector.cursor = 0
	m.flareSelector.offset = 0
	m.rebuildFlareTable()
	return m, nil
}

func (m model) handleKeyMsg(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch m.mode {
	case modeMain:
		return m.handleMainKeys(msg)
	case modeCacheView:
		return m.handleCacheViewKeys(msg)
	case modeCacheDelete:
		return m.handleCacheDeleteKeys(msg)
	case modeWavelength:
		return m.handleWavelengthKeys(msg)
	case modeDateRange:
		return m.handleDateKeys(msg)
	case modeFlare:
		return m.handleFlareFilterKeys(msg)
	case modeSelectFlares:
		return m.handleSelectFlaresKeys(msg)
	default:
		return m, nil
	}
}

func (m model) handleMouseMsg(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
	switch m.mode {
	case modeMain:
		return m.handleMainMouse(msg)
	case modeCacheView:
		var cmd tea.Cmd
		m.cache.viewport, cmd = m.cache.viewport.Update(msg)
		return m, cmd
	case modeCacheDelete:
		return m.handleCacheDeleteMouse(msg)
	case modeWavelength:
		return m.handleWavelengthMouse(msg)
	case modeFlare:
		return m.handleFlareMouse(msg)
	case modeSelectFlares:
		return m.handleSelectFlaresMouse(msg)
	default:
		return m, nil
	}
}

// Mode handlers

func (m model) handleMainKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	if m.cache.menuOpen {
		switch msg.String() {
		case "ctrl+c":
			return m, tea.Quit
		case "esc", "left":
			m.cache.menuOpen = false
			return m, nil
		case "up", "k":
			if m.cache.selected > 0 {
				m.cache.selected--
			}
			return m, nil
		case "down", "j":
			if m.cache.selected < len(m.cache.menuItems)-1 {
				m.cache.selected++
			}
			return m, nil
		case "enter", " ":
			if m.cache.selected >= 0 && m.cache.selected < len(m.cache.menuItems) {
				return m.handleCacheMenuAction(m.cache.menuItems[m.cache.selected])
			}
			return m, nil
		}
	}

	switch msg.String() {
	case "ctrl+c", "esc":
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
			return m.handleMenuSelection(m.menuItems[m.selected])
		}
	}
	return m, nil
}

func (m model) handleCacheViewKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "ctrl+c":
		return m, tea.Quit
	case "esc":
		m.mode = modeMain
		m.notice = "Cache view closed"
		m.noticeSet = m.frame
		return m, nil
	}
	var vpCmd tea.Cmd
	m.cache.viewport, vpCmd = m.cache.viewport.Update(msg)
	return m, vpCmd
}

func (m model) handleCacheDeleteKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	if m.cache.searching {
		switch msg.Type {
		case tea.KeyEsc:
			m.cache.searching = false
			m.cache.searchInput = ""
			m.applyCacheFilter("", m.width)
			m.ensureCacheVisible()
			return m, nil
		case tea.KeyEnter:
			m.cache.searching = false
			m.applyCacheFilter(m.cache.searchInput, m.width)
			m.ensureCacheVisible()
			return m, nil
		case tea.KeyBackspace:
			if len(m.cache.searchInput) > 0 {
				m.cache.searchInput = m.cache.searchInput[:len(m.cache.searchInput)-1]
				m.applyCacheFilter(m.cache.searchInput, m.width)
				m.ensureCacheVisible()
			}
			return m, nil
		case tea.KeyRunes:
			m.cache.searchInput += msg.String()
			m.applyCacheFilter(m.cache.searchInput, m.width)
			m.ensureCacheVisible()
			return m, nil
		case tea.KeySpace:
			m.cache.searchInput += " "
			m.applyCacheFilter(m.cache.searchInput, m.width)
			m.ensureCacheVisible()
			return m, nil
		}
	}

	switch msg.String() {
	case "ctrl+c":
		return m, tea.Quit
	case "esc", "left":
		m.mode = modeMain
		m.notice = "Canceled cache deletion"
		m.noticeSet = m.frame
	case "/":
		m.cache.searching = true
		m.cache.searchInput = ""
		m.cache.cursor = 0
		m.cache.offset = 0
		return m, nil
	case "up", "k":
		if m.cache.cursor > 0 {
			m.cache.cursor--
			m.ensureCacheVisible()
		}
	case "down", "j":
		rows := m.cache.filtered
		if rows == nil {
			rows = m.cache.rows
		}
		if m.cache.cursor < len(rows)-1 {
			m.cache.cursor++
			m.ensureCacheVisible()
		}
	case "tab":
		rows := m.cache.filtered
		if rows == nil {
			rows = m.cache.rows
		}
		if m.cache.cursor >= 0 && m.cache.cursor < len(rows) {
			if idx := m.cacheOriginalIndex(m.cache.cursor); idx >= 0 {
				m.cache.pick[idx] = !m.cache.pick[idx]
			}
		}
	case "enter":
		if len(m.cache.pick) == 0 {
			m.mode = modeMain
			m.notice = "No rows selected."
			m.noticeSet = m.frame
			break
		}
		if err := saveCachePruned(m.cache.header, m.cache.rows, m.cache.pick); err != nil {
			m.notice = fmt.Sprintf("Delete failed: %v", err)
		} else {
			m.notice = fmt.Sprintf("Deleted %d rows", len(m.cache.pick))
			header, rows, err := loadCache()
			if err == nil {
				m.cache.header = header
				m.cache.rows = rows
				m.cache.pick = make(map[int]bool)
				m.applyCacheFilter("", m.width)
				if m.width > 0 && m.height > 0 {
					m.cache.viewport.Width = maxInt(m.width-6, 20)
					m.cache.viewport.Height = maxInt(m.height-10, 8)
				}
				m.cache.viewport.SetContent(m.cache.content)
			} else {
				m.cache.rows = nil
				m.cache.pick = make(map[int]bool)
			}
		}
		m.noticeSet = m.frame
		m.mode = modeMain
	}
	return m, nil
}

func (m model) handleWavelengthKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "ctrl+c":
		return m, tea.Quit
	case "ctrl+a":
		allSelected := true
		for _, opt := range m.wave.options {
			if !m.wave.selected[opt.code] {
				allSelected = false
				break
			}
		}
		next := true
		if allSelected {
			next = false
		}
		for _, opt := range m.wave.options {
			m.wave.selected[opt.code] = next
		}
	case "esc":
		m.mode = modeMain
		m.notice = "Canceled wavelength edit"
		m.noticeSet = m.frame
	case "up", "k":
		if m.wave.focus > 0 {
			m.wave.focus--
		}
	case "down", "j":
		if m.wave.focus < len(m.wave.options)-1 {
			m.wave.focus++
		}
	case " ":
		m.toggleWave(m.wave.focus)
	case "enter":
		m.cfg.wave = buildWaveValue(m.wave.options, m.wave.selected)
		if err := saveConfig(m.cfg); err != nil {
			m.notice = fmt.Sprintf("Save failed: %v", err)
			m.noticeSet = m.frame
		} else {
			m.notice = "Wavelength saved"
			m.noticeSet = m.frame
		}
		m.mode = modeMain
	}
	return m, nil
}

func (m model) handleDateKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	handled := true
	switch msg.String() {
	case "ctrl+c":
		return m, tea.Quit
	case "esc":
		m.mode = modeMain
		m.notice = "Canceled date edit"
		m.noticeSet = m.frame
	case "tab", "down":
		m.date.focus = 1
	case "shift+tab", "up":
		m.date.focus = 0
	case "enter":
		start := strings.TrimSpace(m.date.start)
		end := strings.TrimSpace(m.date.end)
		if start == "" {
			start = strings.TrimSpace(m.cfg.start)
		}
		if end == "" {
			end = strings.TrimSpace(m.cfg.end)
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
		m.cfg.start = start
		m.cfg.end = end
		if err := saveConfig(m.cfg); err != nil {
			m.notice = fmt.Sprintf("Save failed: %v", err)
			m.noticeSet = m.frame
			break
		}
		m.notice = "Date range saved"
		m.noticeSet = m.frame
		m.mode = modeMain
	case "backspace", "delete":
		if m.date.focus == 0 {
			if len(m.date.start) > 0 {
				m.date.start = m.date.start[:len(m.date.start)-1]
			}
		} else {
			if len(m.date.end) > 0 {
				m.date.end = m.date.end[:len(m.date.end)-1]
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
				target := &m.date.start
				if m.date.focus == 1 {
					target = &m.date.end
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
	return m, nil
}

func (m model) handleFlareFilterKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "ctrl+c":
		return m, tea.Quit
	case "esc":
		m.mode = modeMain
		m.notice = "Canceled flare filter edit"
		m.noticeSet = m.frame
	case "tab", "right", "l":
		m.flareFilter.focus = (m.flareFilter.focus + 1) % 3
		m.flareFilter.focusFrame = m.frame
	case "shift+tab", "left":
		m.flareFilter.focus--
		if m.flareFilter.focus < 0 {
			m.flareFilter.focus = 2
		}
		m.flareFilter.focusFrame = m.frame
	case "up", "k":
		switch m.flareFilter.focus {
		case 0:
			if m.flareFilter.compIdx > 0 {
				m.flareFilter.compIdx--
			}
		case 1:
			if m.flareFilter.letterIdx > 0 {
				m.flareFilter.letterIdx--
			}
		case 2:
			if m.flareFilter.magIdx > 0 {
				m.flareFilter.magIdx--
			}
		}
	case "down", "j":
		switch m.flareFilter.focus {
		case 0:
			if m.flareFilter.compIdx < len(m.flareFilter.compDisplays)-1 {
				m.flareFilter.compIdx++
			}
		case 1:
			if m.flareFilter.letterIdx < len(m.flareFilter.classLetters)-1 {
				m.flareFilter.letterIdx++
			}
		case 2:
			if m.flareFilter.magIdx < len(m.flareFilter.magnitudes)-1 {
				m.flareFilter.magIdx++
			}
		}
	case "enter":
		compVal := m.flareFilter.comps[m.flareFilter.compIdx].value
		letter := m.flareFilter.classLetters[m.flareFilter.letterIdx]
		mag := m.flareFilter.magnitudes[m.flareFilter.magIdx]
		if compVal == "All" {
			m.cfg.comparator = "All"
			m.cfg.flareClass = "Any"
		} else {
			m.cfg.comparator = compVal
			m.cfg.flareClass = fmt.Sprintf("%s%s", letter, mag)
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
	return m, nil
}

func (m model) handleSelectFlaresKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "ctrl+c":
		return m, tea.Quit
	case "esc":
		m.mode = modeMain
		m.notice = "Canceled flare selection"
		m.noticeSet = m.frame
	case " ":
		if m.flareSelector.cursor >= 0 && m.flareSelector.cursor < len(m.flareSelector.list) {
			m.flareSelector.selected[m.flareSelector.cursor] = !m.flareSelector.selected[m.flareSelector.cursor]
		}
	case "enter":
		if len(m.flareSelector.selected) == 0 {
			m.notice = "No flares selected."
			m.noticeSet = m.frame
			m.mode = modeMain
			break
		}
		if err := saveFlareSelection(m.flareSelector.header, m.flareSelector.list, m.flareSelector.selected); err != nil {
			m.notice = fmt.Sprintf("Save failed: %v", err)
			m.noticeSet = m.frame
		} else {
			m.notice = fmt.Sprintf("Saved %d flares", len(m.flareSelector.selected))
			m.noticeSet = m.frame
		}
		m.mode = modeMain
	case "up", "k":
		if m.flareSelector.cursor > 0 {
			m.flareSelector.cursor--
		}
		m.ensureFlareVisible()
	case "down", "j":
		if m.flareSelector.cursor < len(m.flareSelector.list)-1 {
			m.flareSelector.cursor++
		}
		m.ensureFlareVisible()
	}
	return m, nil
}

// Mouse handlers

func (m model) handleMainMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
	if m.cache.menuOpen {
		switch msg.Button {
		case tea.MouseButtonWheelUp:
			if m.cache.selected > 0 {
				m.cache.selected--
			}
		case tea.MouseButtonWheelDown:
			if m.cache.selected < len(m.cache.menuItems)-1 {
				m.cache.selected++
			}
		case tea.MouseButtonNone:
			if idx, ok := m.cacheMenuIndexAt(msg.X, msg.Y); ok {
				m.cache.selected = idx
			}
		case tea.MouseButtonLeft:
			if msg.Action == tea.MouseActionRelease {
				return m.handleCacheMenuAction(m.cache.menuItems[m.cache.selected])
			}
		}
		return m, nil
	}

	if msg.Button == tea.MouseButtonNone && msg.Action == tea.MouseActionMotion {
		if idx, ok := m.cacheMenuIndexAt(msg.X, msg.Y); ok {
			m.cache.selected = idx
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
				return m.handleMenuSelection(m.menuItems[m.selected])
			}
		}
	}
	return m, nil
}

func (m model) handleCacheDeleteMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
	switch msg.Button {
	case tea.MouseButtonWheelUp:
		if m.cache.cursor > 0 {
			m.cache.cursor--
			m.ensureCacheVisible()
		}
	case tea.MouseButtonWheelDown:
		if m.cache.cursor < len(m.cache.rows)-1 {
			m.cache.cursor++
			m.ensureCacheVisible()
		}
	case tea.MouseButtonLeft:
		if msg.Action == tea.MouseActionRelease {
			if m.cache.cursor >= 0 && m.cache.cursor < len(m.cache.rows) {
				m.cache.pick[m.cache.cursor] = !m.cache.pick[m.cache.cursor]
			}
		}
	}
	return m, nil
}

func (m model) handleWavelengthMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
	if msg.Button == tea.MouseButtonNone && msg.Action == tea.MouseActionMotion {
		if idx, ok := m.waveIndexAt(msg.X, msg.Y); ok {
			m.wave.focus = idx
		}
	}
	if msg.Button == tea.MouseButtonLeft && msg.Action == tea.MouseActionRelease {
		if idx, ok := m.waveIndexAt(msg.X, msg.Y); ok {
			m.wave.focus = idx
			m.toggleWave(idx)
		}
	}
	return m, nil
}

func (m model) handleFlareMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
	col, row, ok := m.flareHit(msg.X, msg.Y)
	if msg.Button == tea.MouseButtonNone && msg.Action == tea.MouseActionMotion && ok {
		m.flareFilter.focus = col
	}
	switch msg.Button {
	case tea.MouseButtonWheelUp:
		switch m.flareFilter.focus {
		case 0:
			if m.flareFilter.compIdx > 0 {
				m.flareFilter.compIdx--
			}
		case 1:
			if m.flareFilter.letterIdx > 0 {
				m.flareFilter.letterIdx--
			}
		case 2:
			if m.flareFilter.magIdx > 0 {
				m.flareFilter.magIdx--
			}
		}
	case tea.MouseButtonWheelDown:
		switch m.flareFilter.focus {
		case 0:
			if m.flareFilter.compIdx < len(m.flareFilter.compDisplays)-1 {
				m.flareFilter.compIdx++
			}
		case 1:
			if m.flareFilter.letterIdx < len(m.flareFilter.classLetters)-1 {
				m.flareFilter.letterIdx++
			}
		case 2:
			if m.flareFilter.magIdx < len(m.flareFilter.magnitudes)-1 {
				m.flareFilter.magIdx++
			}
		}
	case tea.MouseButtonLeft:
		if ok && msg.Action == tea.MouseActionRelease {
			m.flareFilter.focus = col
			switch col {
			case 0:
				m.flareFilter.compIdx = clampInt(row, 0, len(m.flareFilter.compDisplays)-1)
			case 1:
				m.flareFilter.letterIdx = clampInt(row, 0, len(m.flareFilter.classLetters)-1)
			case 2:
				m.flareFilter.magIdx = clampInt(row, 0, len(m.flareFilter.magnitudes)-1)
			}
		}
	}
	return m, nil
}

func (m model) handleSelectFlaresMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
	switch msg.Button {
	case tea.MouseButtonWheelUp:
		if m.flareSelector.cursor > 0 {
			m.flareSelector.cursor--
			m.ensureFlareVisible()
		}
	case tea.MouseButtonWheelDown:
		if m.flareSelector.cursor < len(m.flareSelector.list)-1 {
			m.flareSelector.cursor++
			m.ensureFlareVisible()
		}
	case tea.MouseButtonLeft:
		if msg.Action == tea.MouseActionRelease {
			if m.flareSelector.cursor >= 0 && m.flareSelector.cursor < len(m.flareSelector.list) {
				m.flareSelector.selected[m.flareSelector.cursor] = !m.flareSelector.selected[m.flareSelector.cursor]
			}
		}
	}
	return m, nil
}

// Menu/cache helpers

func (m model) handleMenuSelection(choice string) (tea.Model, tea.Cmd) {
	switch choice {
	case "Edit Wavelength":
		m.cache.menuOpen = false
		m.mode = modeWavelength
		m.wave.selected = parseWaves(m.cfg.wave)
		m.wave.focus = 0
		m.notice = ""
		m.noticeSet = m.frame
	case "Edit Date Range":
		m.cache.menuOpen = false
		m.mode = modeDateRange
		m.date.start = ""
		m.date.end = ""
		m.date.focus = 0
		m.notice = ""
		m.noticeSet = m.frame
	case "Edit Flare Class Filter":
		m.cache.menuOpen = false
		m.mode = modeFlare
		m.flareFilter.compIdx, m.flareFilter.letterIdx, m.flareFilter.magIdx = parseFlareSelection(m.cfg, m.flareFilter.comps, m.flareFilter.classLetters)
		m.flareFilter.focus = 0
		m.flareFilter.focusFrame = m.frame
		m.notice = ""
		m.noticeSet = m.frame
	case "Select Flares":
		if strings.TrimSpace(m.cfg.start) == "" || strings.TrimSpace(m.cfg.end) == "" {
			m.notice = "Set a date range first."
			m.noticeSet = m.frame
			break
		}
		if strings.TrimSpace(m.cfg.wave) == "" {
			m.notice = "Select at least one wavelength first."
			m.noticeSet = m.frame
			break
		}
		if strings.TrimSpace(m.cfg.comparator) == "" {
			m.notice = "Set a comparator first."
			m.noticeSet = m.frame
			break
		}
		m.cache.menuOpen = false
		m.mode = modeSelectFlares
		m.flareSelector.loading = true
		m.flareSelector.loadError = ""
		m.flareSelector.selected = make(map[int]bool)
		m.flareSelector.cursor = 0
		m.flareSelector.offset = 0
		m.flareSelector.list = nil
		m.flareSelector.header = ""
		m.notice = ""
		m.noticeSet = 0
		return m, loadFlaresCmd(m.cfg)
	case "Cache Options":
		m.cache.menuOpen = true
		m.cache.openFrame = m.frame
		m.cache.selected = 0
		m.notice = ""
		m.noticeSet = m.frame
	case "Quit":
		return m, tea.Quit
	default:
		m.notice = fmt.Sprintf("Selected: %s (not implemented yet)", choice)
		m.noticeSet = m.frame
	}
	return m, nil
}

func (m model) handleCacheMenuAction(action string) (tea.Model, tea.Cmd) {
	switch action {
	case "Back":
		m.cache.menuOpen = false
		m.notice = "Cache menu closed"
		m.noticeSet = m.frame
	case "View Cache":
		header, rows, err := loadCache()
		m.cache.menuOpen = false
		if err != nil {
			header = "description\tflare_class\tstart\tend\tcoordinates\twavelength"
			rows = nil
		}
		m.cache.header = header
		m.cache.rows = rows
		m.applyCacheFilter("", m.width)
		if m.width > 0 && m.height > 0 {
			m.cache.viewport.Width = maxInt(m.width-6, 20)
			m.cache.viewport.Height = maxInt(m.height-10, 8)
		} else {
			m.cache.viewport.Width = 80
			m.cache.viewport.Height = 20
		}
		m.cache.viewport.SetContent(m.cache.content)
		m.mode = modeCacheView
	case "Delete Rows":
		header, rows, err := loadCache()
		m.cache.menuOpen = false
		if err != nil || len(rows) == 0 {
			m.notice = "Cache empty or missing"
			m.noticeSet = m.frame
			return m, nil
		}
		m.cache.header = header
		m.cache.rows = rows
		m.applyCacheFilter("", m.width)
		m.cache.searching = true
		m.cache.searchInput = ""
		m.cache.cursor = 0
		m.cache.offset = 0
		m.cache.pick = make(map[int]bool)
		m.mode = modeCacheDelete
	case "Clear Cache":
		m.cache.menuOpen = false
		if _, err := clearCacheFile(); err != nil {
			m.notice = fmt.Sprintf("Clear failed: %v", err)
		} else {
			m.notice = "Cleared flare cache"
		}
		m.noticeSet = m.frame
	}
	return m, nil
}
