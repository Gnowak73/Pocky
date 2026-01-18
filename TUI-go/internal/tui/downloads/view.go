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
	modeLabel := "Parser"
	if state.TerminalMode == TerminalEmulator {
		modeLabel = "Emulator"
	}
	lines = append(lines, FieldLine{"Terminal Mode", modeLabel})

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
		"Terminal Mode": "Output renderer (parser is default)",
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
	confirmLine := ""
	if state.Confirming {
		confirmLine = "\n\n" + renderConfirmBox(width, state.ConfirmChoice)
	}
	return "\n\n\n\n" + placed + "\n\n" + hintLine + confirmLine + "\n\n\n\n" + helpLine
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
		if state.EventStatus != "" {
			status := styles.Gray.Faint(true).Render(state.EventStatus)
			boxed = boxed + "\n" + status
		}
		hint := "q/esc cancel • ↑/↓ scroll • mouse wheel"
		if state.DonePrompt {
			hint = "Download finished • press enter to return"
		}
		return "\n\n" + boxed + "\n\n" + styles.Gray.Faint(true).Render(hint)
	}
	centered := lipgloss.PlaceHorizontal(width, lipgloss.Center, boxed)
	if state.EventStatus != "" {
		status := styles.Gray.Faint(true).Render(state.EventStatus)
		centered += "\n" + lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, status)
	}
	helpText := "q/esc cancel • ↑/↓ scroll • mouse wheel"
	if state.DonePrompt {
		helpText = "Download finished • press enter to return"
	}
	help := styles.Gray.Faint(true).Render(helpText)
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	return "\n\n" + centered + "\n\n" + helpLine
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

func renderConfirmBox(width int, choice int) string {
	title := styles.LightGray.Render("Proceed with Download?")
	yesStyle := styles.LightGray
	noStyle := styles.LightGray
	if choice == 0 {
		yesStyle = styles.PinkOption
	} else {
		noStyle = styles.PinkOption
	}
	yes := yesStyle.Render("Yes")
	no := noStyle.Render("No")
	choices := lipgloss.JoinHorizontal(lipgloss.Center, yes, "   ", no)

	box := lipgloss.NewStyle().
		Border(lipgloss.NormalBorder()).
		BorderForeground(styles.Purple.GetForeground()).
		Padding(1, 2).
		Render(lipgloss.JoinVertical(lipgloss.Center, title, choices))
	if width <= 0 {
		return box
	}
	return lipgloss.Place(width, lipgloss.Height(box), lipgloss.Center, lipgloss.Top, box)
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
	// return the pointer for the focused, editable line in the rendered form.
	lines := formLines(*state)
	if focus < 0 || focus >= len(lines) {
		return nil
	}
	line := lines[focus]
	switch line.Label {
	case "Provider":
		return nil
	case "Terminal Mode":
		return nil
	case "Email":
		return &state.Form.Email
	case "TSV Path":
		return &state.Form.TSVPath
	case "Output Dir":
		return &state.Form.OutDir
	case "Max Conn":
		return &state.Form.MaxConn
	case "Max Splits":
		return &state.Form.MaxSplits
	case "Attempts":
		return &state.Form.Attempts
	case "Cadence":
		return &state.Form.Cadence
	case "Pad Before":
		return &state.Form.PadBefore
	case "Pad After":
		return &state.Form.PadAfter
	default:
		return nil
	}
}
