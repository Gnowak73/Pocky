package main

import (
	"fmt"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

// The cycle of the TUI is Init() -> return tea.Cmd function -> eval tea.Cmd
// Then we go into the loop of Update() -> return model + tea.Cmd -> View()
// -> eval tea.Cmd from Update -> Update()

// Tea will automatically take messages and pass them etc.
// tea.Cmd is a function type that returns a tea.Msg to tell the TUI to update.
// We will start with a tick function that will start the initial animations for menus.

func tick() tea.Cmd {
	// We take the time, plug it into the function, return a tick Msg empty struct
	// Note that tea.Msg is an empty interfact type, so any type (such as tickMsg)
	// can be used to satisfy tea.Msg.

	return tea.Tick(time.Millisecond*80, func(time.Time) tea.Msg { return tickMsg{} })
}

func (m model) Init() tea.Cmd {
	// to start, we get a tickMsg then we move to Update()
	return tick()
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	// we input a message, then return an updated model along with another
	// message through tea.Cmd

	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		if msg.Width > 0 && msg.Height > 0 {
			m.cache.viewport.Width = max(msg.Width-6, 20)
			m.cache.viewport.Height = max(msg.Height-10, 8)
			if m.mode == modeCacheView && m.cache.content != "" {
				// we need to to set new content that matches the smaller
				// window size in view cache
				m.cache.viewport.SetContent(m.cache.content)
			}
		}
	case tickMsg:
		// frame is the global animation counter
		m.frame++
		// for now we are passing m.logo.lines through each frame. Im sure in
		// the future we may find a more efficient method
		m.logo.colored = colorizeLogo(m.logo.lines, m.logo.blockW, m.frame)
		if m.menu.notice != "" && m.menu.noticeFrame > 0 && m.frame-m.menu.noticeFrame > 19 {
			m.menu.notice = ""
		}
		if m.flare.sel.loading && len(m.spinner.frames) > 0 {
			m.spinner.index = (m.spinner.index + 1) % len(m.spinner.frames)
		}
		// if we started with a tickMsg we end by calling another to
		// keep animations going
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
	m.flare.sel.loading = false
	if msg.err != nil {
		m.flare.sel.loadError = msg.err.Error()
		m.menu.notice = m.flare.sel.loadError
		m.menu.noticeFrame = m.frame
		m.mode = modeMain
		return m, nil
	}
	m.flare.sel.list = msg.entries
	m.flare.sel.header = msg.header
	m.flare.sel.selected = make(map[int]bool)
	if len(m.flare.sel.list) == 0 {
		m.menu.notice = "No flares found."
		m.menu.noticeFrame = m.frame
		m.mode = modeMain
		return m, nil
	}
	m.flare.sel.cursor = 0
	m.flare.sel.offset = 0
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
		if m.menu.selected > 0 {
			m.menu.selected--
		}
	case "down", "j":
		if m.menu.selected < len(m.menu.items)-1 {
			m.menu.selected++
		}
	case "enter", " ":
		if m.menu.selected >= 0 && m.menu.selected < len(m.menu.items) {
			return m.handleMenuSelection(m.menu.items[m.menu.selected])
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
		m.menu.notice = "Cache view closed"
		m.menu.noticeFrame = m.frame
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
		m.menu.notice = "Canceled cache deletion"
		m.menu.noticeFrame = m.frame
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
			m.menu.notice = "No rows selected."
			m.menu.noticeFrame = m.frame
			break
		}
		if err := saveCachePruned(m.cache.header, m.cache.rows, m.cache.pick); err != nil {
			m.menu.notice = fmt.Sprintf("Delete failed: %v", err)
		} else {
			m.menu.notice = fmt.Sprintf("Deleted %d rows", len(m.cache.pick))
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
		m.menu.noticeFrame = m.frame
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
		m.menu.notice = "Canceled wavelength edit"
		m.menu.noticeFrame = m.frame
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
			m.menu.notice = fmt.Sprintf("Save failed: %v", err)
			m.menu.noticeFrame = m.frame
		} else {
			m.menu.notice = "Wavelength saved"
			m.menu.noticeFrame = m.frame
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
		m.menu.notice = "Canceled date edit"
		m.menu.noticeFrame = m.frame
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
			m.menu.notice = "Dates must be YYYY-MM-DD"
			m.menu.noticeFrame = m.frame
			break
		}
		if !chronological(start, end) {
			m.menu.notice = "Start must be on/before End"
			m.menu.noticeFrame = m.frame
			break
		}
		m.cfg.start = start
		m.cfg.end = end
		if err := saveConfig(m.cfg); err != nil {
			m.menu.notice = fmt.Sprintf("Save failed: %v", err)
			m.menu.noticeFrame = m.frame
			break
		}
		m.menu.notice = "Date range saved"
		m.menu.noticeFrame = m.frame
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
		m.menu.notice = "Canceled flare filter edit"
		m.menu.noticeFrame = m.frame
	case "tab", "right", "l":
		m.flare.filter.focus = (m.flare.filter.focus + 1) % 3
		m.flare.filter.focusFrame = m.frame
	case "shift+tab", "left":
		m.flare.filter.focus--
		if m.flare.filter.focus < 0 {
			m.flare.filter.focus = 2
		}
		m.flare.filter.focusFrame = m.frame
	case "up", "k":
		switch m.flare.filter.focus {
		case 0:
			if m.flare.filter.compIdx > 0 {
				m.flare.filter.compIdx--
			}
		case 1:
			if m.flare.filter.letterIdx > 0 {
				m.flare.filter.letterIdx--
			}
		case 2:
			if m.flare.filter.magIdx > 0 {
				m.flare.filter.magIdx--
			}
		}
	case "down", "j":
		switch m.flare.filter.focus {
		case 0:
			if m.flare.filter.compIdx < len(m.flare.filter.compDisplays)-1 {
				m.flare.filter.compIdx++
			}
		case 1:
			if m.flare.filter.letterIdx < len(m.flare.filter.classLetters)-1 {
				m.flare.filter.letterIdx++
			}
		case 2:
			if m.flare.filter.magIdx < len(m.flare.filter.magnitudes)-1 {
				m.flare.filter.magIdx++
			}
		}
	case "enter":
		compVal := m.flare.filter.comps[m.flare.filter.compIdx].value
		letter := m.flare.filter.classLetters[m.flare.filter.letterIdx]
		mag := m.flare.filter.magnitudes[m.flare.filter.magIdx]
		if compVal == "All" {
			m.cfg.comparator = "All"
			m.cfg.flareClass = "Any"
		} else {
			m.cfg.comparator = compVal
			m.cfg.flareClass = fmt.Sprintf("%s%s", letter, mag)
		}
		if err := saveConfig(m.cfg); err != nil {
			m.menu.notice = fmt.Sprintf("Save failed: %v", err)
			m.menu.noticeFrame = m.frame
			break
		}
		m.menu.notice = "Flare filter saved"
		m.menu.noticeFrame = m.frame
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
		m.menu.notice = "Canceled flare selection"
		m.menu.noticeFrame = m.frame
	case " ":
		if m.flare.sel.cursor >= 0 && m.flare.sel.cursor < len(m.flare.sel.list) {
			m.flare.sel.selected[m.flare.sel.cursor] = !m.flare.sel.selected[m.flare.sel.cursor]
		}
	case "enter":
		if len(m.flare.sel.selected) == 0 {
			m.menu.notice = "No flares selected."
			m.menu.noticeFrame = m.frame
			m.mode = modeMain
			break
		}
		if err := saveFlareSelection(m.flare.sel.header, m.flare.sel.list, m.flare.sel.selected); err != nil {
			m.menu.notice = fmt.Sprintf("Save failed: %v", err)
			m.menu.noticeFrame = m.frame
		} else {
			m.menu.notice = fmt.Sprintf("Saved %d flares", len(m.flare.sel.selected))
			m.menu.noticeFrame = m.frame
		}
		m.mode = modeMain
	case "up", "k":
		if m.flare.sel.cursor > 0 {
			m.flare.sel.cursor--
		}
		m.ensureFlareVisible()
	case "down", "j":
		if m.flare.sel.cursor < len(m.flare.sel.list)-1 {
			m.flare.sel.cursor++
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
			m.menu.selected = idx
		}
	}
	switch msg.Button {
	case tea.MouseButtonWheelUp:
		if m.menu.selected > 0 {
			m.menu.selected--
		}
	case tea.MouseButtonWheelDown:
		if m.menu.selected < len(m.menu.items)-1 {
			m.menu.selected++
		}
	case tea.MouseButtonLeft:
		if idx, ok := m.menuIndexAt(msg.X, msg.Y); ok {
			m.menu.selected = idx
			if msg.Action == tea.MouseActionRelease {
				return m.handleMenuSelection(m.menu.items[m.menu.selected])
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
		m.flare.filter.focus = col
	}
	switch msg.Button {
	case tea.MouseButtonWheelUp:
		switch m.flare.filter.focus {
		case 0:
			if m.flare.filter.compIdx > 0 {
				m.flare.filter.compIdx--
			}
		case 1:
			if m.flare.filter.letterIdx > 0 {
				m.flare.filter.letterIdx--
			}
		case 2:
			if m.flare.filter.magIdx > 0 {
				m.flare.filter.magIdx--
			}
		}
	case tea.MouseButtonWheelDown:
		switch m.flare.filter.focus {
		case 0:
			if m.flare.filter.compIdx < len(m.flare.filter.compDisplays)-1 {
				m.flare.filter.compIdx++
			}
		case 1:
			if m.flare.filter.letterIdx < len(m.flare.filter.classLetters)-1 {
				m.flare.filter.letterIdx++
			}
		case 2:
			if m.flare.filter.magIdx < len(m.flare.filter.magnitudes)-1 {
				m.flare.filter.magIdx++
			}
		}
	case tea.MouseButtonLeft:
		if ok && msg.Action == tea.MouseActionRelease {
			m.flare.filter.focus = col
			switch col {
			case 0:
				m.flare.filter.compIdx = clampInt(row, 0, len(m.flare.filter.compDisplays)-1)
			case 1:
				m.flare.filter.letterIdx = clampInt(row, 0, len(m.flare.filter.classLetters)-1)
			case 2:
				m.flare.filter.magIdx = clampInt(row, 0, len(m.flare.filter.magnitudes)-1)
			}
		}
	}
	return m, nil
}

func (m model) handleSelectFlaresMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
	switch msg.Button {
	case tea.MouseButtonWheelUp:
		if m.flare.sel.cursor > 0 {
			m.flare.sel.cursor--
			m.ensureFlareVisible()
		}
	case tea.MouseButtonWheelDown:
		if m.flare.sel.cursor < len(m.flare.sel.list)-1 {
			m.flare.sel.cursor++
			m.ensureFlareVisible()
		}
	case tea.MouseButtonLeft:
		if msg.Action == tea.MouseActionRelease {
			if m.flare.sel.cursor >= 0 && m.flare.sel.cursor < len(m.flare.sel.list) {
				m.flare.sel.selected[m.flare.sel.cursor] = !m.flare.sel.selected[m.flare.sel.cursor]
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
		m.menu.notice = ""
		m.menu.noticeFrame = m.frame
	case "Edit Date Range":
		m.cache.menuOpen = false
		m.mode = modeDateRange
		m.date.start = ""
		m.date.end = ""
		m.date.focus = 0
		m.menu.notice = ""
		m.menu.noticeFrame = m.frame
	case "Edit Flare Class Filter":
		m.cache.menuOpen = false
		m.mode = modeFlare
		m.flare.filter.compIdx, m.flare.filter.letterIdx, m.flare.filter.magIdx = parseFlareSelection(m.cfg, m.flare.filter.comps, m.flare.filter.classLetters)
		m.flare.filter.focus = 0
		m.flare.filter.focusFrame = m.frame
		m.menu.notice = ""
		m.menu.noticeFrame = m.frame
	case "Select Flares":
		if strings.TrimSpace(m.cfg.start) == "" || strings.TrimSpace(m.cfg.end) == "" {
			m.menu.notice = "Set a date range first."
			m.menu.noticeFrame = m.frame
			break
		}
		if strings.TrimSpace(m.cfg.wave) == "" {
			m.menu.notice = "Select at least one wavelength first."
			m.menu.noticeFrame = m.frame
			break
		}
		if strings.TrimSpace(m.cfg.comparator) == "" {
			m.menu.notice = "Set a comparator first."
			m.menu.noticeFrame = m.frame
			break
		}
		m.cache.menuOpen = false
		m.mode = modeSelectFlares
		m.flare.sel.loading = true
		m.flare.sel.loadError = ""
		m.flare.sel.selected = make(map[int]bool)
		m.flare.sel.cursor = 0
		m.flare.sel.offset = 0
		m.flare.sel.list = nil
		m.flare.sel.header = ""
		m.menu.notice = ""
		m.menu.noticeFrame = 0
		return m, loadFlaresCmd(m.cfg)
	case "Cache Options":
		m.cache.menuOpen = true
		m.cache.openFrame = m.frame
		m.cache.selected = 0
		m.menu.notice = ""
		m.menu.noticeFrame = m.frame
	case "Quit":
		return m, tea.Quit
	default:
		m.menu.notice = fmt.Sprintf("Selected: %s (not implemented yet)", choice)
		m.menu.noticeFrame = m.frame
	}
	return m, nil
}

func (m model) handleCacheMenuAction(action string) (tea.Model, tea.Cmd) {
	switch action {
	case "Back":
		m.cache.menuOpen = false
		m.menu.notice = "Cache menu closed"
		m.menu.noticeFrame = m.frame
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
			m.menu.notice = "Cache empty or missing"
			m.menu.noticeFrame = m.frame
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
			m.menu.notice = fmt.Sprintf("Clear failed: %v", err)
		} else {
			m.menu.notice = "Cleared flare cache"
		}
		m.menu.noticeFrame = m.frame
	}
	return m, nil
}
