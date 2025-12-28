package chrome

// chrome/menu.go lives in chrome because it only renders menu blocks from the
// MenuState passed in—no mode routing or key handling happens here. Keeping the
// presentation primitives in chrome keeps the Bubble Tea routing in core where it
// belongs. Menu.go is the renderer for the main meny, returning the strings to be
// printed to the TUI

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
	lgtbl "github.com/charmbracelet/lipgloss/table"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/styles"
	"github.com/pocky/tui-go/internal/tui/utils"
)

type MenuState struct {
	Items       []string
	Selected    int    // and index representing the chosen option (corresponds to mode #)
	Notice      string // the message that will appear on the bottom
	NoticeFrame int    // the frame of the message to keep track of its fading animation
}

type CacheMenuView struct {
	Open      bool // the status of whether the little submenu is open or not
	Items     []string
	Selected  int // the index of the selection option
	OpenFrame int // the frame counter captures when the submenu was opened for the animation
}

func RenderMenu(width int, menu MenuState, noticeLine string, cache *CacheMenuView, frame int) string {
	// the goal is to return a string to print to the TUI, reflecting the state of the
	// main menu. We will need a separate function for the cache submenu since it has
	// its own different animation going on and a change in the layout of the window.

	// since lines may be of different width, we must create a buffer slice to hold the
	// styled lines, which are separated centered and positioned, before putting them together

	lines, cacheIndex := buildMenuRows(menu)

	if cache != nil && cache.Open && cacheIndex >= 0 {
		lines = insertCacheSubmenu(lines, cacheIndex, *cache, frame)
	}

	menuBlock := strings.Join(lines, "\n")
	helpText := "↑/↓ select • h/j/k/l Vim • enter submit"
	if cache != nil && cache.Open {
		helpText += " • esc close cache"
	}

	// menu is rendered first, so we keep a safeguard in case at launch the window size hasn't been reported yet
	// where we dont use lipgloss.Place. Rather, we just stack everything on the left-hand side.
	if width <= 0 {
		help := styles.LightGray.Render(helpText)
		if noticeLine != "" {
			return "\n\n" + menuBlock + "\n\n" + "  " + noticeLine + "\n\n" + help
		}
		return "\n\n" + menuBlock + "\n\n" + help
	}

	placed := lipgloss.Place(
		width-2,
		lipgloss.Height(menuBlock),
		lipgloss.Center, lipgloss.Top,
		menuBlock,
	)

	help := lipgloss.Place(
		width,
		1, lipgloss.Center,
		lipgloss.Top,
		styles.LightGray.Render(helpText),
	)

	block := "\n\n" + placed
	if noticeLine != "" {
		block += "\n\n" + noticeLine
	}
	return block + "\n\n" + help
}

func renderCacheSubmenu(cache CacheMenuView, frame int) string {
	// we need a var for the frame and how many rows of submenu are currently visibile during expand animation,
	// along with fraction of how far we are through animation to drive color fade
	delta := max(frame-cache.OpenFrame, 0)
	targetHeight := len(cache.Items) + 2                 // borders + rows
	heightAnim := max(min(targetHeight, (delta+1)*2), 1) // dictates speed, 2 rows per tick currently
	progress := min(float64(delta)/float64(targetHeight), 1)

	col := utils.BlendHex(styles.SubcacheStart, styles.SubcacheEnd, progress)
	if heightAnim >= targetHeight {
		col = styles.SubcacheFinal
	}

	rowPadLeft := 0
	rowPadRight := 2
	style := styles.VeryLightGray.Padding(0, rowPadRight, 0, rowPadLeft)
	cursorStyle := styles.MenuSelected.Padding(0, rowPadRight, 0, rowPadLeft)

	//  we want to compute a stable width so the table doesn't resize when selection changes
	maxLabel := 0
	for _, item := range cache.Items {
		maxLabel = max(maxLabel, lipgloss.Width("  "+item))
		maxLabel = max(maxLabel, lipgloss.Width("» "+item))
	}

	rows := make([][]string, 0, len(cache.Items))
	for i, item := range cache.Items {
		label := "  " + item
		if i == cache.Selected {
			label = "» " + item
		}
		if pad := maxLabel - lipgloss.Width(label); pad > 0 {
			label += strings.Repeat(" ", pad)
		}
		rows = append(rows, []string{label})
	}

	t := lgtbl.New().
		Border(lipgloss.RoundedBorder()).
		BorderStyle(lipgloss.NewStyle().Foreground(lipgloss.Color(col))).
		Rows(rows...).
		StyleFunc(func(row, col int) lipgloss.Style {
			if row == cache.Selected {
				return cursorStyle
			}
			return style
		})

	tableStr := t.String()
	tableStr = lipgloss.NewStyle().MarginLeft(2).Render(tableStr)

	if heightAnim < lipgloss.Height(tableStr) {
		lines := strings.Split(tableStr, "\n")
		if heightAnim > len(lines) {
			heightAnim = len(lines)
		}
		tableStr = strings.Join(lines[:heightAnim], "\n")
	}

	return tableStr
}

func MenuIndexAt(x, y int, width int, logo LogoState, cfg config.Config, menu MenuState, cache *CacheMenuView, frame int) (int, bool) {
	// we need a way to map the mouse location to the cursor on the main menu
	// We need our cursor position with respect to the top of the menu, or
	// how far down from the start of the rendered menu block

	if x < 0 || y < 0 {
		return 0, false
	}

	// we will create the entire renderered menu block and use the dimensions to check
	// for the mouse being on the application
	box, versionLine, w := RenderLogoHeader(width, logo)
	summary := RenderSummary(cfg, w)
	header := box + "\n" + versionLine + summary

	if cache != nil && cache.Open {
		lines, cacheOptLine := buildMenuRows(menu)
		if cacheOptLine == -1 {
			return 0, false
		}
		lines = insertCacheSubmenu(lines, cacheOptLine, *cache, frame)
		subStart := cacheOptLine + 1
		itemStart := subStart + 1
		_, row, ok := utils.MouseHit(utils.MouseHitSpec{
			X:        x,
			Y:        y,
			Width:    w,
			Header:   header,
			Block:    strings.Join(lines, "\n"),
			TopPad:   1,
			CheckX:   false,
			RowStart: itemStart,
			RowCount: len(cache.Items),
		})
		return row, ok
	}

	menuView := RenderMenu(w, menu, "", nil, 0)
	_, row, ok := utils.MouseHit(utils.MouseHitSpec{
		X:        x,
		Y:        y,
		Width:    w,
		Header:   header,
		Block:    menuView,
		TopPad:   0,
		CheckX:   false,
		RowStart: 1,
		RowCount: len(menu.Items),
	})
	return row, ok
}

func RenderLogoHeader(width int, logo LogoState) (string, string, int) {
	// we need a centralized code to return the shared logo box, version line, in rendering + view.go
	content := strings.Join(logo.Colored, "\n")
	boxLogo := styles.LogoBox.Render(content)

	w := width
	if w <= 0 {
		w = lipgloss.Width(boxLogo)
	}

	box := lipgloss.Place(
		w,
		lipgloss.Height(boxLogo),
		lipgloss.Center, lipgloss.Top,
		boxLogo,
	)

	boxWidth := lipgloss.Width(boxLogo)
	versionText := styles.Version.Render("VERSION: 0.2")
	leftPad := 0
	if w > boxWidth {
		leftPad = (w - boxWidth) / 2
	}

	versionLine := strings.Repeat(" ", leftPad) +
		lipgloss.Place(boxWidth, 1, lipgloss.Right, lipgloss.Top, versionText)

	return box, versionLine, w
}

func buildMenuRows(menu MenuState) ([]string, int) {
	// calculate the width of the widest item so every line can be placed consistently
	maxText := 0
	for _, item := range menu.Items {
		maxText = max(maxText, lipgloss.Width(item))
	}

	var lines []string
	cacheIndex := -1

	for i, item := range menu.Items {
		style := styles.MenuItem
		cursor := "  "
		if i == menu.Selected {
			style = styles.MenuSelected
			cursor = style.Render("> ")
		}
		lineContent := cursor + style.Render(item)
		line := lipgloss.PlaceHorizontal(maxText, lipgloss.Center, lineContent)
		lines = append(lines, line)

		// set cache index to real value if we are entering submenu
		if item == "Cache Options" {
			cacheIndex = len(lines) - 1
		}
	}

	return lines, cacheIndex
}

func insertCacheSubmenu(lines []string, cacheIndex int, cache CacheMenuView, frame int) []string {
	// upon opening, we need to append the new submenu lines to the body.
	// To prevent mutating the original original lines, we will copy the
	// results to a new empty slice literal []string{}

	subBlock := renderCacheSubmenu(cache, frame)
	subLines := strings.Split(subBlock, "\n")
	prefix := append([]string{}, lines[:cacheIndex+1]...)
	prefix = append(prefix, subLines...)
	return append(prefix, lines[cacheIndex+1:]...)
}
