package downloads

import (
	"math"
	"strings"

	"github.com/charmbracelet/lipgloss"
	lgtbl "github.com/charmbracelet/lipgloss/table"
	"github.com/pocky/tui-go/internal/tui/styles"
)

type FieldLine struct {
	Label string
	Value string
}

func formLines(state DownloadState) []FieldLine {
	// given the state of the download fields and the menu, we will return the lines for
	// the input fields which will be presented to the users

	form := state.Form
	lines := []FieldLine{}

	if state.Protocol == ProtocolFido {
		lines = append(lines, FieldLine{"Provider", string(form.Provider)})
	}
	if state.Protocol == ProtocolDRMS || form.Provider == ProviderJSOC {
		lines = append(lines, FieldLine{"Email", form.Email})
	}

	lines = append(lines,
		FieldLine{"TSV Path", form.TSVPath},
		FieldLine{"Output Dir", form.OutDir},
		FieldLine{"Max Conn", form.MaxConn},
		FieldLine{"Max Splits", form.MaxSplits},
		FieldLine{"Attempts", form.Attempts},
		FieldLine{"Cadence", form.Cadence},
		FieldLine{"Pad Before", form.PadBefore},
		FieldLine{"Pad After", form.PadAfter},
	)
	return lines
}

func RenderForm(state DownloadState, width int) string {
	// these hints will persist at the bottom of the table for the user
	hints := map[string]string{
		"TSV Path":   "Path to flare cache TSV",
		"Output Dir": "Where FITS will be saved",
		"Max Conn":   "Downloader max connections (default 6)",
		"Max Splits": "Per-file Downloader max split count (default 3)",
		"Attempts":   "Max attempts per window/wavelength (default 5)",
		"Cadence":    "Time in between FITs snapshots (typically 12s)",
		"Pad Before": "Minutes before event start",
		"Pad After":  "Minutes after event start (Blank = to event end)",
		"Email":      "JSOC Email (env JSOC_EMAIL used if blank)",
		"Provider":   "Fido provider (space toggles jsoc/vso)",
	}

	// given the state and the width of the application window, we will return a
	// rendered string that will present the form line. We will render only the current
	// focused line from the formLines.

	lines := formLines(state)

	labelStyle := styles.LightGray
	valueStyle := styles.VeryLightGray
	focusStyle := styles.PinkOption
	ghostStyle := styles.LightGray.Faint(true)
	help := styles.LightGray.Render("↑/↓ move • type to edit • backspace delete • enter run • esc back")

	t := lgtbl.New()
	t = t.Headers("ARGUMENTS FORM")
	t = t.Border(lipgloss.NormalBorder())
	t = t.BorderStyle(styles.Purple)
	t = t.StyleFunc(func(row, col int) lipgloss.Style {
		if row == lgtbl.HeaderRow {
			return styles.SummaryHeader.Bold(true).Align(lipgloss.Center)
		}
		bodyRow := row - 1
		if bodyRow%2 == 0 {
			return styles.Gray.Padding(0, 2, 0, 1)
		}

		return styles.LightGray.Padding(0, 2, 0, 1)
	})

	for idx, line := range lines {
		val := line.Value
		if strings.TrimSpace(val) == "" {
			val = ghostStyle.Render("<unset>")
		} else {
			val = valueStyle.Render(val)
		}
		rawLabel := line.Label + ":"
		label := labelStyle.Render(rawLabel)
		if idx == state.Focus {
			label = focusStyle.Render(rawLabel) // only label highlighted
		}
		row := label + " " + val
		t = t.Row(row)
	}

	tableStr := t.String()

	hint := ""
	if state.Focus >= 0 && state.Focus < len(lines) {
		if h, ok := hints[lines[state.Focus].Label]; ok {
			hint = h
		}
	}

	hintLine := styles.Gray.Faint(true).Render(hint)
	hintLine = lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, hintLine)

	placed := lipgloss.Place(
		width,
		lipgloss.Height(tableStr),
		lipgloss.Center,
		lipgloss.Top,
		tableStr,
	)

	helpLine := lipgloss.Place(
		width,
		1,
		lipgloss.Center,
		lipgloss.Top,
		help,
	)
	return "\n\n\n\n" + placed + "\n\n" + hintLine + "\n\n\n\n" + helpLine
}

func RenderRun(state DownloadState, width int) string {
	body := state.Viewport.View()
	scrollbar := renderScrollbar(state.Viewport.Height, state.Viewport.ScrollPercent())
	content := lipgloss.JoinHorizontal(lipgloss.Top, body, scrollbar)
	boxed := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(styles.FaintGray.GetForeground()).
		Padding(0, 0, 0, 1).
		Render(content)
	if width <= 0 {
		return "\n\n" + boxed
	}
	centered := lipgloss.PlaceHorizontal(width, lipgloss.Center, boxed)
	return "\n\n" + centered
}

func renderScrollbar(height int, percent float64) string {
	if height <= 0 {
		return ""
	}
	pos := 0
	if height > 1 {
		pos = int(math.Round(percent * float64(height-1)))
	}
	var rows []string
	for i := 0; i < height; i++ {
		ch := styles.FaintGray.Render("│")
		if i == pos {
			ch = styles.PinkOption.Render("█")
		}
		rows = append(rows, ch)
	}
	return lipgloss.JoinVertical(lipgloss.Left, rows...)
}

func FormLines(state DownloadState) []FieldLine {
	return formLines(state)
}

func DeleteFormChar(state *DownloadState, focus int) {
	// intead of doing this like done in dates.go and update_dates.go, we would like to have
	// a general helper that can be used on any of the field lines so we don't hardcode each case.
	// We need a target which points towards the form field value we are typing.
	target := FormFieldPtr(state, focus)
	if target == nil {
		return
	}
	if len(*target) > 0 {
		*target = (*target)[:len(*target)-1] // move back one rune
	}
}

func AppendFormRunes(state *DownloadState, focus int, runes []rune) {
	// we append on a rune to the target string
	target := FormFieldPtr(state, focus)
	if target == nil {
		return
	}
	*target += string(runes)
}

func FormFieldPtr(state *DownloadState, focus int) *string {
	fields := []*string{} // slice of pointers to actual string fields
	// we will return the pointer which our focus is currently on for typing rune inputs

	// Provider is display-only; shift focus if Fido
	if state.Protocol == ProtocolFido {
		if focus == 0 {
			return nil
		}
		focus--
	}

	if state.Protocol == ProtocolDRMS || state.Form.Provider == ProviderJSOC {
		fields = append(fields, &state.Form.Email)
	}

	fields = append(fields,
		&state.Form.TSVPath,
		&state.Form.OutDir,
		&state.Form.MaxConn,
		&state.Form.MaxSplits,
		&state.Form.Attempts,
		&state.Form.Cadence,
		&state.Form.PadBefore,
		&state.Form.PadAfter,
	)

	if focus < 0 || focus >= len(fields) {
		return nil
	}
	return fields[focus]
}
