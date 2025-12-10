package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/charmbracelet/lipgloss"
	lgtbl "github.com/charmbracelet/lipgloss/table"
)

func cacheFilePath() string {
	return filepath.Join("..", "flare_cache.tsv")
}

func loadCache() (string, []flareEntry, error) {
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
	var rows []flareEntry
	for _, line := range lines[1:] {
		if strings.TrimSpace(line) == "" {
			continue
		}
		fields := strings.Split(line, "\t")
		row := flareEntry{full: line}
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

func cacheViewHeight(m model) int {
	n := len(m.cache.rows)
	if m.mode == modeCacheDelete && (len(m.cache.filtered) > 0 || m.cache.filter != "") {
		n = len(m.cache.filtered)
	}
	if n == 0 {
		return 0
	}
	return maxInt(7, minInt(25, n))
}

// filterCacheRows returns rows matching the query (case-insensitive) plus their original indices.
func filterCacheRows(rows []flareEntry, query string) ([]flareEntry, []int) {
	q := strings.ToLower(strings.TrimSpace(query))
	if q == "" {
		idx := make([]int, len(rows))
		for i := range rows {
			idx[i] = i
		}
		return rows, idx
	}

	var out []flareEntry
	var idx []int
	for i, r := range rows {
		if strings.Contains(strings.ToLower(r.desc), q) ||
			strings.Contains(strings.ToLower(r.class), q) ||
			strings.Contains(strings.ToLower(r.start), q) ||
			strings.Contains(strings.ToLower(r.end), q) ||
			strings.Contains(strings.ToLower(r.coord), q) ||
			strings.Contains(strings.ToLower(r.wave), q) {
			out = append(out, r)
			idx = append(idx, i)
		}
	}
	return out, idx
}

// cacheOriginalIndex maps a filtered row index back to the original flareEntrys index.
func (m model) cacheOriginalIndex(filteredIdx int) int {
	if filteredIdx < 0 {
		return -1
	}
	if len(m.cache.filterIdx) > 0 && filteredIdx < len(m.cache.filterIdx) {
		return m.cache.filterIdx[filteredIdx]
	}
	if filteredIdx < len(m.cache.rows) {
		return filteredIdx
	}
	return -1
}

// applyCacheFilter updates filtered rows, cursor bounds, and rendered content.
func (m *model) applyCacheFilter(query string, width int) {
	m.cache.filter = strings.TrimSpace(query)
	m.cache.filtered, m.cache.filterIdx = filterCacheRows(m.cache.rows, m.cache.filter)
	if len(m.cache.filtered) == 0 {
		m.cache.cursor = 0
		m.cache.offset = 0
	} else if m.cache.cursor >= len(m.cache.filtered) {
		m.cache.cursor = len(m.cache.filtered) - 1
	}
	m.cache.content = renderCacheTableString(m.cache.filtered, width)
	m.ensureCacheVisible()
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

func saveCachePruned(header string, rows []flareEntry, delete map[int]bool) error {
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

func cacheHeaderView(m model, width int) string {
	title := lipgloss.NewStyle().
		BorderStyle(lipgloss.RoundedBorder()).
		Padding(0, 1).
		Render("flare_cache.tsv")
	line := strings.Repeat("─", maxInt(0, m.cache.viewport.Width-lipgloss.Width(title)))
	return lipgloss.JoinHorizontal(lipgloss.Center, title, line)
}

func cacheFooterView(m model, width int) string {
	info := lipgloss.NewStyle().
		BorderStyle(lipgloss.RoundedBorder()).
		Padding(0, 1).
		Render(fmt.Sprintf("%3.0f%%", m.cache.viewport.ScrollPercent()*100))
	line := strings.Repeat("─", maxInt(0, m.cache.viewport.Width-lipgloss.Width(info)))
	return lipgloss.JoinHorizontal(lipgloss.Center, line, info)
}

// renderCacheTableString builds a styled table (similar to previous layout).
func renderCacheTableString(rows []flareEntry, width int) string {
	if width <= 0 {
		width = 80
	}
	rowCap, descCap := 4, 3
	classCap, startCap, endCap, coordCap, waveCap := 8, 32, 32, 30, 18
	if width > 0 {
		switch {
		case width < 70:
			classCap, startCap, endCap, coordCap, waveCap = 5, 12, 12, 9, 10
		case width < 90:
			classCap, startCap, endCap, coordCap, waveCap = 7, 18, 18, 14, 14
		case width < 110:
			classCap, startCap, endCap, coordCap, waveCap = 9, 22, 22, 18, 18
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

func renderCacheView(m model, width int) string {
	rows := m.cache.filtered
	if rows == nil {
		rows = m.cache.rows
	}
	availWidth := width
	if availWidth > 0 {
		availWidth = maxInt(availWidth-6, 20)
	}
	m.cache.content = renderCacheTableString(rows, availWidth)
	contentWidth := lipgloss.Width(m.cache.content)
	contentHeight := lipgloss.Height(m.cache.content)
	targetW := minInt(maxInt(contentWidth+2, 20), maxInt(availWidth-2, 20))
	targetH := minInt(contentHeight+2, maxInt(m.height-10, 5))
	m.cache.viewport.Width = targetW
	m.cache.viewport.Height = targetH
	centered := centerContent(m.cache.content, m.cache.viewport.Width)
	m.cache.viewport.SetContent(centered)

	header := cacheHeaderView(m, width)
	footer := cacheFooterView(m, width)
	help := menuHelpStyle.Render("↑/↓ scroll • pgup/pgdown jump • esc back")

	box := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("#8B5EDB")).
		Padding(0, 1).
		Width(m.cache.viewport.Width + 2)

	centeredView := lipgloss.Place(
		m.cache.viewport.Width,
		lipgloss.Height(m.cache.viewport.View()),
		lipgloss.Center,
		lipgloss.Top,
		m.cache.viewport.View(),
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
	return "\n\n" + placed
}

func renderCacheDelete(m model, width int) string {
	title := summaryHeaderStyle.Copy().Bold(false).Render("Delete Cache Rows (Scroll)")
	height := cacheViewHeight(m)
	rows := m.cache.filtered
	if rows == nil {
		rows = m.cache.rows
	}
	if len(rows) == 0 {
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

	start := clampInt(m.cache.offset, 0, maxInt(len(rows)-height, 0))
	end := minInt(len(rows), start+height)

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

	maxClass, maxStart, maxEnd, maxCoord, maxWave := 12, 26, 26, 22, 18
	if width > 0 {
		switch {
		case width < 70:
			maxClass, maxStart, maxEnd, maxCoord, maxWave = 4, 10, 10, 8, 6
		case width < 90:
			maxClass, maxStart, maxEnd, maxCoord, maxWave = 6, 14, 14, 10, 8
		case width < 110:
			maxClass, maxStart, maxEnd, maxCoord, maxWave = 8, 18, 18, 14, 11
		}
	}

	tableRows := make([][]string, 0, end-start)
	for i := start; i < end; i++ {
		r := rows[i]
		orig := m.cacheOriginalIndex(i)
		sel := "[ ]"
		if orig >= 0 && m.cache.pick[orig] {
			sel = selMark.Render("[x]")
		}
		desc := "..."
		tableRows = append(tableRows, []string{
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
		Rows(tableRows...).
		StyleFunc(func(row, col int) lipgloss.Style {
			if row == lgtbl.HeaderRow {
				return headerStyle
			}
			abs := start + row
			if abs == m.cache.cursor {
				return cursorStyle
			}
			if abs%2 == 0 {
				return rowEven
			}
			return rowOdd
		})

	tableStr := t.String()
	searchText := m.cache.filter
	if m.cache.searching {
		searchText = m.cache.searchInput + "▌"
	}
	searchLine := menuHelpStyle.Render(fmt.Sprintf("Search: %s", searchText))
	help := menuHelpStyle.Render("↑/↓ move • / search (space ok) • tab toggle • enter delete • esc cancel")
	innerW := lipgloss.Width(tableStr)
	if w := lipgloss.Width(title); w > innerW {
		innerW = w
	}
	if w := lipgloss.Width(searchLine); w > innerW {
		innerW = w
	}
	if w := lipgloss.Width(help); w > innerW {
		innerW = w
	}
	if innerW == 0 {
		innerW = width
	}
	titleLine := lipgloss.Place(innerW, lipgloss.Height(title), lipgloss.Center, lipgloss.Top, title)
	searchBlock := lipgloss.Place(innerW, lipgloss.Height(searchLine), lipgloss.Center, lipgloss.Top, searchLine)
	tableBlock := lipgloss.Place(innerW, lipgloss.Height(tableStr), lipgloss.Center, lipgloss.Top, tableStr)
	helpLine := lipgloss.Place(innerW, 1, lipgloss.Center, lipgloss.Top, help)

	body := lipgloss.JoinVertical(lipgloss.Center, titleLine, "", searchBlock, "", tableBlock, helpLine)
	effW := width
	if effW <= 0 {
		effW = innerW
	}
	if innerW > effW {
		effW = innerW
	}
	return "\n\n" + lipgloss.Place(effW, lipgloss.Height(body), lipgloss.Center, lipgloss.Top, body)
}

// ensureCacheVisible keeps the cache cursor within the viewport.
func (m *model) ensureCacheVisible() {
	h := cacheViewHeight(*m)
	if h <= 0 {
		m.cache.offset = 0
		return
	}
	rows := m.cache.filtered
	if rows == nil || m.mode != modeCacheDelete {
		rows = m.cache.rows
	}
	if m.cache.cursor < 0 {
		m.cache.cursor = 0
	}
	if m.cache.cursor >= len(rows) {
		m.cache.cursor = len(rows) - 1
	}
	if m.cache.cursor < m.cache.offset {
		m.cache.offset = m.cache.cursor
	}
	if m.cache.cursor >= m.cache.offset+h {
		m.cache.offset = m.cache.cursor - h + 1
	}
	maxOffset := maxInt(len(rows)-h, 0)
	if m.cache.offset > maxOffset {
		m.cache.offset = maxOffset
	}
	if m.cache.offset < 0 {
		m.cache.offset = 0
	}
}
