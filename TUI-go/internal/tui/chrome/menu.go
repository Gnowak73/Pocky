package chrome

// chrome/menu.go lives in chrome because it only renders menu blocks from the
// MenuState passed in—no mode routing or key handling happens here. Keeping the
// presentation primitives in chrome keeps the Bubble Tea routing in core where it
// belongs. Menu.go is the renderer for the main meny, returning the strings to be
// printed to the TUI

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/styles"
	"github.com/pocky/tui-go/internal/tui/theme"
)

type MenuState struct {
	Items       []string
	Selected    int
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

	maxText := 0
	cacheIndex := -1 // -1 is a sentinel value, tracks where "Cache Options" row sits in the  "lines" slice
	var lines []string

	for _, item := range menu.Items {
		maxText = max(maxText, lipgloss.Width(item))
	}

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

	if cache != nil && cache.Open && cacheIndex >= 0 {
		// upon opening, we need to append the new submenu lines to the body.
		// To prevent mutating the original original lines, we will copy the
		// results to a new empty slice literal []string{}

		copy := append([]string{}, lines[:cacheIndex+1]...) // slices are half-open ranges, hence the +1
		copy = append(copy, renderCacheSubmenu(*cache, frame))
		copy = append(copy, lines[cacheIndex+1:]...)
		lines = copy
	}

	menuBlock := strings.Join(lines, "\n")
	helpText := "↑/k up • ↓/j down • enter submit"
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

func padLine(s string, width int) string {
	// we want to enforce a minimum width by appending spaces
	if pad := width - lipgloss.Width(s); pad > 0 {
		return s + strings.Repeat(" ", pad)
	}
	return s
}

func renderCacheSubmenu(cache CacheMenuView, frame int) string {
	maxCache := 0 // max width for the submenu
	for _, item := range cache.Items {
		maxCache = max(maxCache, lipgloss.Width(item))
	}

	innerWidth := maxCache + 4 // extra width for breathing room, same with height
	targetHeight := len(cache.Items) + 2

	// we need a var for the frame and how many rows of submenu are currently visibile during expand animation,
	// along with fraction of how far we are through animation to drive color fade
	delta := max(frame-cache.OpenFrame, 0)
	heightAnim := max(min(targetHeight, (delta+1)*3), 1) // grow by 3 row per tick, at least 1 row
	progress := min(float64(delta)/float64(targetHeight), 1)

	col := theme.BlendHex(styles.SubcacheStart, styles.SubcacheEnd, progress)
	if heightAnim >= targetHeight {
		col = styles.SubcacheFinal
	}
	boxStyle := lipgloss.NewStyle().Foreground(lipgloss.Color(col))

	var rows []string
	top := boxStyle.Render("   ╭" + strings.Repeat("─", innerWidth) + "╮")
	bottom := boxStyle.Render("   ╰" + strings.Repeat("─", innerWidth) + "╯")
	leftBar := boxStyle.Render("   │")
	rightBar := boxStyle.Render("│")

	rows = append(rows, top)

	if heightAnim >= targetHeight {
		for j, subItem := range cache.Items {
			style := styles.VeryLightGray
			cursor := "  "
			if j == cache.Selected {
				style = styles.MenuSelected
				cursor = styles.MenuSelected.Render("» ")
			}

			// we use padLine so every cache option occupies same horizontal space before wrapping
			line := padLine(cursor+style.Render(subItem), innerWidth)
			rows = append(rows, leftBar+line+rightBar)
		}
		rows = append(rows, bottom)
	} else {
		mid := max(heightAnim-1, 0) // we need to append "mid" empty rows to rows

		for range mid {
			rows = append(rows, leftBar+strings.Repeat(" ", innerWidth)+rightBar)
		}
	}
	return strings.Join(rows, "\n")
}

func MenuIndexAt(x, y int, width int, logo LogoState, cfg config.Config, menu MenuState) (int, bool) {
	if y < 0 || x < 0 || len(menu.Items) == 0 {
		return 0, false
	}

	content := strings.Join(logo.Colored, "\n")
	boxContent := styles.LogoBox.Render(content)

	w := width
	if w <= 0 {
		w = lipgloss.Width(boxContent)
	}
	box := lipgloss.Place(w, lipgloss.Height(boxContent), lipgloss.Center, lipgloss.Top, boxContent)

	boxWidth := lipgloss.Width(boxContent)
	versionText := styles.Version.Render("VERSION: 0.2")
	leftPad := 0
	if w > boxWidth {
		leftPad = (w - boxWidth) / 2
	}
	versionLine := strings.Repeat(" ", leftPad) + lipgloss.Place(boxWidth, 1, lipgloss.Right, lipgloss.Top, versionText)

	summary := RenderSummary(cfg, w)
	menuView := RenderMenu(w, menu, "", nil, 0)

	header := box + "\n" + versionLine + summary
	menuTop := lipgloss.Height(header)
	menuHeight := lipgloss.Height(menuView)
	if y < menuTop || y >= menuTop+menuHeight {
		return 0, false
	}

	relativeY := y - menuTop
	start := 1
	itemY := relativeY - start
	if itemY < 0 || itemY >= len(menu.Items) {
		return 0, false
	}

	return itemY, true
}

// CacheMenuIndexAt maps mouse coords to a cache submenu item when open.
func CacheMenuIndexAt(x, y int, width int, logo LogoState, cfg config.Config, menu MenuState, cache CacheMenuView) (int, bool) {
	if !cache.Open {
		return 0, false
	}

	content := strings.Join(logo.Colored, "\n")
	boxContent := styles.LogoBox.Render(content)

	w := width
	if w <= 0 {
		w = lipgloss.Width(boxContent)
	}
	box := lipgloss.Place(w, lipgloss.Height(boxContent), lipgloss.Center, lipgloss.Top, boxContent)

	boxWidth := lipgloss.Width(boxContent)
	versionText := styles.Version.Render("VERSION: 0.2")
	leftPad := 0
	if w > boxWidth {
		leftPad = (w - boxWidth) / 2
	}
	versionLine := strings.Repeat(" ", leftPad) + lipgloss.Place(boxWidth, 1, lipgloss.Right, lipgloss.Top, versionText)

	summary := RenderSummary(cfg, w)
	header := box + "\n" + versionLine + summary
	menuTop := max(lipgloss.Height(header)+1, 0)

	var lines []string
	maxText := 0
	for _, item := range menu.Items {
		if val := lipgloss.Width(item); val > maxText {
			maxText = val
		}
	}

	cacheOptLine := -1
	for _, item := range menu.Items {
		cursor := "  "
		cursorW := lipgloss.Width(cursor)
		lineContent := cursor + styles.MenuItem.Render(item)
		line := lipgloss.PlaceHorizontal(maxText+cursorW, lipgloss.Center, lineContent)
		lines = append(lines, line)
		if item == "Cache Options" {
			cacheOptLine = len(lines) - 1
			maxCache := 0
			for _, it := range cache.Items {
				if w := lipgloss.Width(it); w > maxCache {
					maxCache = w
				}
			}
			innerWidth := maxCache + 4
			lines = append(lines, "   ╭"+strings.Repeat("─", innerWidth)+"╮")
			for _, subItem := range cache.Items {
				sLine := "  " + styles.MenuItem.Render(subItem)
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
	subStart := cacheOptLine + 1
	itemStart := subStart + 1
	if relativeY < itemStart || relativeY >= itemStart+len(cache.Items) {
		return 0, false
	}
	idx := relativeY - itemStart
	if idx < 0 || idx >= len(cache.Items) {
		return 0, false
	}
	return idx, true
}
