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
		return m.handleFlaresLoaded(msg)
	case tea.KeyMsg:
		return m.handleKeyMsg(msg)
	case tea.MouseMsg:
		return m.handleMouseMsg(msg)
	}
	return m, nil
}

func (m model) handleFlaresLoaded(msg flaresLoadedMsg) (tea.Model, tea.Cmd) {
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
		m.cacheViewport, cmd = m.cacheViewport.Update(msg)
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
	if m.cacheMenuOpen {
		switch msg.String() {
		case "ctrl+c":
			return m, tea.Quit
		case "esc", "left":
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
				return m.handleCacheMenuAction(m.cacheMenuItems[m.cacheSelected])
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
	m.cacheViewport, vpCmd = m.cacheViewport.Update(msg)
	return m, vpCmd
}

func (m model) handleCacheDeleteKeys(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	if m.cacheSearching {
		switch msg.Type {
		case tea.KeyEsc:
			m.cacheSearching = false
			m.cacheSearchInput = ""
			m.applyCacheFilter("", m.width)
			m.ensureCacheVisible()
			return m, nil
		case tea.KeyEnter:
			m.cacheSearching = false
			m.applyCacheFilter(m.cacheSearchInput, m.width)
			m.ensureCacheVisible()
			return m, nil
		case tea.KeyBackspace:
			if len(m.cacheSearchInput) > 0 {
				m.cacheSearchInput = m.cacheSearchInput[:len(m.cacheSearchInput)-1]
				m.applyCacheFilter(m.cacheSearchInput, m.width)
				m.ensureCacheVisible()
			}
			return m, nil
		case tea.KeyRunes:
			m.cacheSearchInput += msg.String()
			m.applyCacheFilter(m.cacheSearchInput, m.width)
			m.ensureCacheVisible()
			return m, nil
		case tea.KeySpace:
			m.cacheSearchInput += " "
			m.applyCacheFilter(m.cacheSearchInput, m.width)
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
		m.cacheSearching = true
		m.cacheSearchInput = ""
		m.cacheCursor = 0
		m.cacheOffset = 0
		return m, nil
	case "up", "k":
		if m.cacheCursor > 0 {
			m.cacheCursor--
			m.ensureCacheVisible()
		}
	case "down", "j":
		rows := m.cacheFiltered
		if rows == nil {
			rows = m.cacheRows
		}
		if m.cacheCursor < len(rows)-1 {
			m.cacheCursor++
			m.ensureCacheVisible()
		}
	case "tab":
		rows := m.cacheFiltered
		if rows == nil {
			rows = m.cacheRows
		}
		if m.cacheCursor >= 0 && m.cacheCursor < len(rows) {
			if idx := m.cacheOriginalIndex(m.cacheCursor); idx >= 0 {
				m.cachePick[idx] = !m.cachePick[idx]
			}
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
			header, rows, err := loadCache()
			if err == nil {
				m.cacheHeader = header
				m.cacheRows = rows
				m.cachePick = make(map[int]bool)
				m.applyCacheFilter("", m.width)
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
		m.dateFocus = 1
	case "shift+tab", "up":
		m.dateFocus = 0
	case "enter":
		start := strings.TrimSpace(m.dateStart)
		end := strings.TrimSpace(m.dateEnd)
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
		m.flareFocus = (m.flareFocus + 1) % 3
		m.flareFocusFrame = m.frame
	case "shift+tab", "left":
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
			if m.flareCompIdx < len(m.flareCompDisplays)-1 {
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
		compVal := m.flareComps[m.flareCompIdx].value
		letter := m.flareClassLetters[m.flareLetterIdx]
		mag := m.flareMagnitudes[m.flareMagIdx]
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
	}
	return m, nil
}

// Mouse handlers

func (m model) handleMainMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
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
				return m.handleCacheMenuAction(m.cacheMenuItems[m.cacheSelected])
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
				return m.handleMenuSelection(m.menuItems[m.selected])
			}
		}
	}
	return m, nil
}

func (m model) handleCacheDeleteMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
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
			if m.cacheCursor >= 0 && m.cacheCursor < len(m.cacheRows) {
				m.cachePick[m.cacheCursor] = !m.cachePick[m.cacheCursor]
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
			if m.flareCompIdx < len(m.flareCompDisplays)-1 {
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
				m.flareCompIdx = clampInt(row, 0, len(m.flareCompDisplays)-1)
			case 1:
				m.flareLetterIdx = clampInt(row, 0, len(m.flareClassLetters)-1)
			case 2:
				m.flareMagIdx = clampInt(row, 0, len(m.flareMagnitudes)-1)
			}
		}
	}
	return m, nil
}

func (m model) handleSelectFlaresMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
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

// Menu/cache helpers

func (m model) handleMenuSelection(choice string) (tea.Model, tea.Cmd) {
	switch choice {
	case "Edit Wavelength":
		m.cacheMenuOpen = false
		m.mode = modeWavelength
		m.wave.selected = parseWaves(m.cfg.wave)
		m.wave.focus = 0
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
		m.flareCompIdx, m.flareLetterIdx, m.flareMagIdx = parseFlareSelection(m.cfg, m.flareComps, m.flareClassLetters)
		m.flareFocus = 0
		m.flareFocusFrame = m.frame
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
		return m, loadFlaresCmd(m.cfg)
	case "Cache Options":
		m.cacheMenuOpen = true
		m.cacheOpenFrame = m.frame
		m.cacheSelected = 0
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
		m.applyCacheFilter("", m.width)
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
		m.applyCacheFilter("", m.width)
		m.cacheSearching = true
		m.cacheSearchInput = ""
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
	return m, nil
}
