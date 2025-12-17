package ui

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/charmbracelet/bubbles/table"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	lgtbl "github.com/charmbracelet/lipgloss/table"
	"github.com/pocky/tui-go/internal/ui/styles"
)

func flareViewHeight(m model) int {
	if len(m.flare.sel.list) == 0 {
		return 0
	}
	return max(7, min(12, len(m.flare.sel.list)))
}

func (m model) styledFlareRows() []table.Row {
	if len(m.flare.sel.list) == 0 {
		return nil
	}
	rows := make([]table.Row, 0, len(m.flare.sel.list))
	for i, entry := range m.flare.sel.list {
		check := "[ ]"
		if m.flare.sel.selected[i] {
			check = "[x]"
		}
		rows = append(rows, table.Row{check, entry.class, entry.start, entry.end, entry.coord})
	}
	return rows
}

func (m *model) rebuildFlareTable() {
	if len(m.flare.sel.list) == 0 {
		m.flare.sel.table = table.Model{}
		return
	}

	wSel, wClass, wstart, wend, wCoord := flareTableWidths(*m)
	columns := []table.Column{
		{Title: "SEL", Width: wSel},
		{Title: "CLASS", Width: wClass},
		{Title: "START", Width: wstart},
		{Title: "END", Width: wend},
		{Title: "COORDINATES", Width: wCoord},
	}

	rows := m.styledFlareRows()
	height := max(7, min(12, len(rows)))
	t := table.New(
		table.WithColumns(columns),
		table.WithRows(rows),
		table.WithHeight(height),
		table.WithFocused(true),
	)
	s := table.DefaultStyles()
	s.Header = s.Header.
		Border(lipgloss.NormalBorder()).
		Inherit(styles.GrayBorder).
		BorderBottom(true).
		Inherit(styles.VeryLightGray).
		Bold(true).
		PaddingLeft(1).
		PaddingRight(1)
	s.Selected = s.Selected.
		Inherit(styles.Gray).
		Background(lipgloss.Color("")).
		Bold(false).
		PaddingLeft(1).
		PaddingRight(1)
	s.Cell = s.Cell.
		Align(lipgloss.Left).
		Inherit(styles.Gray).
		PaddingLeft(1).
		PaddingRight(1)
	t.SetStyles(s)
	t.SetCursor(m.flare.sel.cursor)
	m.flare.sel.table = t
}

func (m *model) updateFlareTableRows() {
	if len(m.flare.sel.list) == 0 || m.flare.sel.table.Columns() == nil {
		return
	}
	rows := m.styledFlareRows()
	m.flare.sel.table.SetRows(rows)
	m.flare.sel.table.SetCursor(m.flare.sel.cursor)
}

func flareTableWidths(m model) (int, int, int, int, int) {
	wSel := lipgloss.Width("SEL")
	if wSel < lipgloss.Width("[x]") {
		wSel = lipgloss.Width("[x]")
	}
	wClass := lipgloss.Width("Class")
	wstart := lipgloss.Width("start")
	wend := lipgloss.Width("end")
	wCoord := lipgloss.Width("Coordinates")
	for _, e := range m.flare.sel.list {
		if w := lipgloss.Width(e.class); w > wClass {
			wClass = w
		}
		if w := lipgloss.Width(e.start); w > wstart {
			wstart = w
		}
		if w := lipgloss.Width(e.end); w > wend {
			wend = w
		}
		if w := lipgloss.Width(e.coord); w > wCoord {
			wCoord = w
		}
	}
	pad := 2
	return wSel + pad, wClass + pad, wstart + pad, wend + pad, wCoord + pad
}

func renderSelectFlares(m model, width int) string {
	title := styles.SummaryHeader.Copy().Bold(false).Render("Choose Flares to Catalogue (Scroll)")

	if m.flare.sel.loading {
		spin := ""
		if len(m.spinner.frames) > 0 {
			spin = m.spinner.frames[m.spinner.index]
		}
		msg := styles.LightGray.Render(fmt.Sprintf("Loading flares %s", spin))
		block := lipgloss.JoinVertical(lipgloss.Center, "", msg)
		if width <= 0 {
			return "\n" + block
		}
		return "\n" + lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	}

	if m.flare.sel.loadError != "" {
		msg := lipgloss.NewStyle().Foreground(lipgloss.Color("#FF6B81")).Render(m.flare.sel.loadError)
		block := lipgloss.JoinVertical(lipgloss.Center, title, "", msg)
		if width <= 0 {
			return "\n\n" + block
		}
		return "\n\n" + lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	}

	if len(m.flare.sel.list) == 0 {
		msg := styles.LightGray.Render("No flares found.")
		block := lipgloss.JoinVertical(lipgloss.Center, title, "", msg)
		if width <= 0 {
			return "\n\n" + block
		}
		return "\n\n" + lipgloss.Place(width, lipgloss.Height(block), lipgloss.Center, lipgloss.Top, block)
	}

	height := flareViewHeight(m)
	if m.flare.sel.cursor < 0 {
		m.flare.sel.cursor = 0
	}
	if height == 0 {
		msg := styles.LightGray.Render("No flares found.")
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
	help := styles.LightGray.Render("↑/↓ move • space toggle • enter save • esc cancel")

	if width <= 0 {
		return "\n\n" + body + "\n\n" + help
	}

	placed := lipgloss.Place(width, lipgloss.Height(body), lipgloss.Center, lipgloss.Top, body)
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	return "\n\n" + placed + "\n\n" + helpLine
}

// renderSelectFlaresTable builds the flare selection table with distinct columns and a selectable SEL column.
func renderSelectFlaresTable(m model, width int, height int) string {
	// we want to build the flare selection table with distinct columns
	// and a selectabel SEL column.
	start := clamp(m.flare.sel.offset, 0, max(len(m.flare.sel.list)-height, 0))
	end := min(len(m.flare.sel.list), start+height)

	base := lipgloss.NewStyle().Padding(0, 1)
	headerStyle := base.Inherit(styles.VeryLightGray).Bold(true)
	cursorStyle := base.Foreground(lipgloss.Color("#F785D1")).Background(lipgloss.Color("#2A262A"))
	selectColStyle := base.Foreground(lipgloss.Color("#C7CDD6"))
	classEvenStyle := base.Inherit(styles.Gray)
	classOddStyle := base.Inherit(styles.VeryLightGray)
	coordEvenStyle := base.Foreground(lipgloss.Color("#B8C3D9"))
	coordOddStyle := base.Foreground(lipgloss.Color("#A0A9BE"))
	startendEvenStyle := base.Inherit(styles.LightGray)
	startendOddStyle := base.Inherit(styles.Gray)
	evenStyle := base.Inherit(styles.Gray)
	oddStyle := base.Inherit(styles.VeryLightGray)
	selMark := lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1"))

	rows := make([][]string, 0, end-start)
	for i := start; i < end; i++ {
		entry := m.flare.sel.list[i]
		sel := "[ ]"
		if m.flare.sel.selected[i] {
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
		BorderStyle(styles.FaintGray).
		Headers("SEL", "CLASS", "START", "END", "COORDINATES").
		Rows(rows...).
		StyleFunc(func(row, col int) lipgloss.Style {
			if row == lgtbl.HeaderRow {
				return headerStyle
			}
			abs := start + row
			if abs == m.flare.sel.cursor {
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
					return startendEvenStyle
				}
				return startendOddStyle
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

func loadFlaresCmd(cfg config) tea.Cmd {
	return func() tea.Msg {
		cmp := comparatorASCII(cfg.comparator)
		if strings.TrimSpace(cfg.start) == "" || strings.TrimSpace(cfg.end) == "" || strings.TrimSpace(cfg.wave) == "" || cmp == "" {
			return flaresLoadedMsg{err: fmt.Errorf("missing required fields")}
		}

		flareClass := cfg.flareClass
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

		cmd := exec.Command("python", "query.py", cfg.start, cfg.end, cmp, flareClass, cfg.wave, tmpPath)
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

// ensureFlareVisible adjusts the offset so the cursor row remains within the viewport.
func (m *model) ensureFlareVisible() {
	h := flareViewHeight(*m)
	if h <= 0 {
		m.flare.sel.offset = 0
		return
	}
	if m.flare.sel.cursor < 0 {
		m.flare.sel.cursor = 0
	}
	if m.flare.sel.cursor >= len(m.flare.sel.list) {
		m.flare.sel.cursor = len(m.flare.sel.list) - 1
	}
	if m.flare.sel.cursor < m.flare.sel.offset {
		m.flare.sel.offset = m.flare.sel.cursor
	}
	if m.flare.sel.cursor >= m.flare.sel.offset+h {
		m.flare.sel.offset = m.flare.sel.cursor - h + 1
	}
	maxOffset := max(len(m.flare.sel.list)-h, 0)
	if m.flare.sel.offset > maxOffset {
		m.flare.sel.offset = maxOffset
	}
	if m.flare.sel.offset < 0 {
		m.flare.sel.offset = 0
	}
}
