package flares

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/charmbracelet/bubbles/viewport"
	"github.com/charmbracelet/lipgloss"
	lgtbl "github.com/charmbracelet/lipgloss/table"
	"github.com/pocky/tui-go/internal/tui/styles"
)

var cacheFilePath = filepath.Join("..", "flare_cache.tsv")

type CacheState struct {
	MenuOpen    bool           // is the submenu open?
	MenuItems   []string       // the items in the submenu
	Selected    int            // the index of selected submenu item
	OpenFrame   int            // the frame when "cache options" was opened (for animation)
	Rows        []Entry        // full unfiltered list of cached flare entries loaded
	Header      string         // the header line from the flare_cache.tsv file for reference to data storage
	Pick        map[int]bool   // map of unfiltered entries and if they are chosen for deletion
	Cursor      int            // the index for currently highlighted row for selection
	Offset      int            // how much left padding is
	Viewport    viewport.Model // bubbles viewport for view cache, built-in mouse and scroll
	Content     string         // rendered table string used by the cache viewport
	Filter      string         // the current search query string
	Filtered    []Entry        // filtered list
	FilterIdx   []int          // a parallel slice to filtered. Each entry stores original index in "Rows" (faster than map)
	Searching   bool           // are we searching in delete mode right now?
	SearchInput string         // the live input string being types while searching is true before commiting to filter
}

func NewCacheState() CacheState {
	return CacheState{
		MenuItems: []string{
			"View Cache",
			"Delete Rows",
			"Clear Cache",
			"Back",
		},
		Pick:     make(map[int]bool),
		Viewport: viewport.New(80, 20), // some safe arbitrary default before scaling in update.go
	}
}

func LoadCache() (string, []Entry, error) {
	data, err := os.ReadFile(cacheFilePath)
	if err != nil {
		return "", nil, err
	}
	lines := strings.Split(strings.TrimRight(string(data), "\n"), "\n")
	header := lines[0] // first line is always header the way we've formatted the cache

	// when parsing through the lines, we will look past the header, for lines 1+. If we see an empty line by
	// coincidence we will just continue and move to the next one. If not, we separate by the tab escape char \t.
	var rows []Entry
	for _, line := range lines[1:] {
		if strings.TrimSpace(line) == "" {
			continue
		}
		fields := strings.Split(line, "\t")
		row := Entry{Full: line} // the original tsv line

		// we add conditions for length to prevent panics, NOTE: later we may add an actual value verification
		if len(fields) > 0 {
			row.Desc = fields[0]
		}
		if len(fields) > 1 {
			row.Class = fields[1]
		}
		if len(fields) > 2 {
			row.Start = fields[2]
		}
		if len(fields) > 3 {
			row.End = fields[3]
		}
		if len(fields) > 4 {
			row.Coord = fields[4]
		}
		if len(fields) > 5 {
			row.Wave = fields[5]
		}
		rows = append(rows, row)
	}
	return header, rows, nil
}

// FilterCacheRows returns rows matching the query (case-insensitive) plus their original indices.
func FilterCacheRows(rows []Entry, query string) ([]Entry, []int) {
	// given a query, we would like to only return the certain rows that match that query
	// across one of the possible table values. We would like this search to be case insensitive.
	// Given this search, we will return a slice of filtered entries and their index mappings to Rows
	// so that when we select them for deletion we delete from Rows. We will input rows as "Rows".

	// to prevent special casing, we will just use an if statement for the empty search to give back
	// all rows with an identity mapping
	q := strings.ToLower(strings.TrimSpace(query))
	if q == "" {
		idx := make([]int, len(rows))
		for i := range rows {
			idx[i] = i
		}
		return rows, idx
	}

	var out []Entry
	var idx []int
	for i, r := range rows {
		if strings.Contains(strings.ToLower(r.Desc), q) ||
			strings.Contains(strings.ToLower(r.Class), q) ||
			strings.Contains(strings.ToLower(r.Start), q) ||
			strings.Contains(strings.ToLower(r.End), q) ||
			strings.Contains(strings.ToLower(r.Coord), q) ||
			strings.Contains(strings.ToLower(r.Wave), q) {
			out = append(out, r)
			idx = append(idx, i) // acts as a map of filterIdx -> rowIdx
		}
	}
	return out, idx
}

func (c *CacheState) ApplyCacheFilter(query string, width int) {
	// Given that we have the new filtered indexes from FilterCacheRows, we need to update
	// the table to only contain these rows. We will also populate content here for the viewport,
	// which will be seen as an application of a "" filter to prevent special case logic.
	c.Filter = strings.TrimSpace(query)
	c.Filtered, c.FilterIdx = FilterCacheRows(c.Rows, c.Filter)
	if len(c.Filtered) == 0 {
		c.Cursor = 0
		c.Offset = 0
	} else if c.Cursor >= len(c.Filtered) {
		c.Cursor = len(c.Filtered) - 1
	}
	c.Content = renderCacheTableString(c.Filtered, width)
}

func ClearCacheFile() (string, error) {
	path := cacheFilePath
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

func SaveCachePruned(header string, rows []Entry, delete map[int]bool) error {
	path := cacheFilePath
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
		if strings.TrimSpace(r.Full) == "" {
			continue
		}
		fmt.Fprintln(f, r.Full)
	}
	if err := f.Close(); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func cacheHeaderView(c CacheState) string {
	title := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		Padding(0, 1).
		Render("flare_cache.tsv")
	line := strings.Repeat("─", max(0, c.Viewport.Width-lipgloss.Width(title)))
	return lipgloss.JoinHorizontal(lipgloss.Center, title, line)
}

func cacheFooterView(c CacheState) string {
	info := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		Padding(0, 1).
		Render(fmt.Sprintf("%3.0f%%", c.Viewport.ScrollPercent()*100))
	line := strings.Repeat("─", max(0, c.Viewport.Width-lipgloss.Width(info)))
	return lipgloss.JoinHorizontal(lipgloss.Center, line, info)
}

// renderCacheTableString builds a styled table (similar to previous layout).
func renderCacheTableString(rows []Entry, width int) string {
	if width <= 0 {
		width = 80
	}
	rowCap, descCap := 4, 3
	classCap, startCap, endCap, coordCap, waveCap := 8, 32, 32, 30, 24
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
	headerStyle := base.Inherit(styles.VeryLightGray).Bold(true)
	rowEven := base.Inherit(styles.Gray)
	rowOdd := base.Inherit(styles.LightGray)
	descStyle := styles.LightGray

	t := lgtbl.New().
		Border(lipgloss.NormalBorder()).
		BorderStyle(styles.FaintGray).
		Headers("ROW", "DESC", "CLASS", "START", "END", "COORD", "WAVE")

	for i, r := range rows {
		rowNum := truncateCell(fmt.Sprintf("%d", i+1), maxWidths[0])
		desc := descStyle.Render(truncateCell("...", maxWidths[1]))
		class := truncateCell(r.Class, maxWidths[2])
		start := truncateCell(r.Start, maxWidths[3])
		end := truncateCell(r.End, maxWidths[4])
		coord := truncateCell(r.Coord, maxWidths[5])
		wave := truncateCell(WaveDisplay(r.Wave), maxWidths[6])
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

func truncateCell(s string, maxW int) string {
	if maxW <= 0 {
		return ""
	}
	runes := []rune(s)
	if len(runes) <= maxW {
		return s
	}
	return string(runes[:maxW])
}

func centerContent(content string, width int) string {
	if width <= 0 {
		return content
	}
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

func (c *CacheState) RenderCacheView(width int, height int) string {
	rows := c.Filtered
	if rows == nil {
		rows = c.Rows
	}
	availWidth := width
	if availWidth > 0 {
		availWidth = max(availWidth-6, 20)
	}
	c.Content = renderCacheTableString(rows, availWidth)
	contentWidth := lipgloss.Width(c.Content)
	contentHeight := lipgloss.Height(c.Content)
	targetW := min(max(contentWidth+2, 20), max(availWidth-2, 20))
	targetH := min(contentHeight+2, max(height-10, 5))
	c.Viewport.Width = targetW
	c.Viewport.Height = targetH
	centered := centerContent(c.Content, c.Viewport.Width)
	c.Viewport.SetContent(centered)

	header := cacheHeaderView(*c)
	footer := cacheFooterView(*c)
	help := styles.LightGray.Render("↑/↓ scroll • pgup/pgdown jump • esc back")

	box := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("#8B5EDB")).
		Padding(0, 1).
		Width(c.Viewport.Width + 2)

	centeredView := lipgloss.Place(
		c.Viewport.Width,
		lipgloss.Height(c.Viewport.View()),
		lipgloss.Center,
		lipgloss.Top,
		c.Viewport.View(),
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

func (c *CacheState) RenderCacheDelete(width int) string {
	title := styles.SummaryHeader.Bold(false).Render("Delete Cache Rows (Scroll)")
	height := c.viewHeight()
	rows := c.Filtered
	if rows == nil {
		rows = c.Rows
	}
	if len(rows) == 0 {
		msg := styles.LightGray.Render("Cache empty.")
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

	start := max(c.Offset, 0)
	if max := max(len(rows)-height, 0); start > max {
		start = max
	}
	end := min(len(rows), start+height)

	base := lipgloss.NewStyle().Padding(0, 1)
	headerStyle := base.Inherit(styles.VeryLightGray).Bold(true)
	rowEven := base.Inherit(styles.Gray)
	rowOdd := base.Inherit(styles.VeryLightGray)
	cursorStyle := base.Foreground(lipgloss.Color("#F785D1")).Background(lipgloss.Color("#2A262A"))
	selMark := lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1"))

	trunc := func(s string, maxLen int) string {
		if maxLen <= 0 {
			return ""
		}
		if len(s) <= maxLen {
			return s
		}
		if maxLen <= 3 {
			return s[:maxLen]
		}
		return s[:maxLen-3] + "..."
	}

	maxClass, maxStart, maxEnd, maxCoord, maxWave := 12, 26, 26, 22, 24
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
		orig := c.CacheOriginalIndex(i)
		sel := "[ ]"
		if orig >= 0 && c.Pick[orig] {
			sel = selMark.Render("[x]")
		}
		desc := "..."
		tableRows = append(tableRows, []string{
			sel,
			desc,
			trunc(r.Class, maxClass),
			trunc(r.Start, maxStart),
			trunc(r.End, maxEnd),
			trunc(r.Coord, maxCoord),
			trunc(WaveDisplay(r.Wave), maxWave),
		})
	}

	t := lgtbl.New().
		Border(lipgloss.NormalBorder()).
		BorderStyle(styles.FaintGray).
		Headers("SEL", "DESC", "CLASS", "START", "END", "COORD", "WAVE").
		Rows(tableRows...).
		StyleFunc(func(row, col int) lipgloss.Style {
			if row == lgtbl.HeaderRow {
				return headerStyle
			}
			abs := start + row
			if abs == c.Cursor {
				return cursorStyle
			}
			if abs%2 == 0 {
				return rowEven
			}
			return rowOdd
		})

	tableStr := t.String()
	searchText := c.Filter
	if c.Searching {
		searchText = c.SearchInput + "▌"
	}
	searchLine := styles.LightGray.Render(fmt.Sprintf("Search: %s", searchText))
	help := styles.LightGray.Render("↑/↓ move • / search (space ok) • tab toggle • enter delete • esc cancel")
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

func (c CacheState) viewHeight() int {
	// It could be that we didnt Filter anything yet and so we get nothing back.
	// This is not the same as having a filter and getting nothing back.
	n := len(c.Filtered)
	if n == 0 && c.Filter == "" { // if no filtering, use full rows
		n = len(c.Rows) // only happens if Filtered hasn't been populated yet
	}
	if n == 0 { // no filtering and result is zero, then no result
		return 0
	}
	return clampHeight(n, 7, 25)
}

// EnsureVisible keeps the cache cursor within the viewport.
func (c *CacheState) EnsureVisible() {
	h := c.viewHeight()
	if h <= 0 {
		c.Offset = 0
		return
	}
	rows := c.Filtered
	if rows == nil {
		rows = c.Rows
	}
	c.Cursor, c.Offset = clampViewport(c.Cursor, c.Offset, len(rows), h)
}

func (c CacheState) CacheOriginalIndex(filteredIdx int) int {
	// map[filtered index] gives the index in terms of the entire "Rows".
	// If there actually are filtered results, FilterIdx will be populated. But if there
	// arent any results, it will have length 0. In the cirsumstance there are no results,
	// then we are directly working with "Rows" and dont need the map.
	if filteredIdx < 0 {
		return -1 // sentinel value
	}
	if len(c.FilterIdx) > 0 && filteredIdx < len(c.FilterIdx) {
		return c.FilterIdx[filteredIdx]
	}
	if filteredIdx < len(c.Rows) {
		return filteredIdx
	}
	return -1
}
