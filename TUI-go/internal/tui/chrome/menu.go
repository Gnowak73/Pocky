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
	lines, cacheIndex := buildMenuLines(menu)
	if cache != nil && cache.Open && cacheIndex >= 0 {
		lines = insertAfter(lines, cacheIndex, renderCacheSubmenu(*cache, frame))
	}
	menuBlock := strings.Join(lines, "\n")
	helpText := "↑/k up • ↓/j down • enter submit"
	if cache != nil && cache.Open {
		helpText += " • esc close cache"
	}
	return renderMenuBlock(width, menuBlock, noticeLine, helpText)
}

func buildMenuLines(menu MenuState) ([]string, int) {
	// maintain a sliding buffer of styled rows so we can return the centered block later
	var lines []string
	maxText := 0
	cacheIndex := -1

	for _, item := range menu.Items {
		maxText = max(maxText, lipgloss.Width(item))
	}

	for i, item := range menu.Items {
		style := styles.MenuItem
		cursor := "  "
		cursorW := lipgloss.Width(cursor)
		if i == menu.Selected {
			style = styles.MenuSelected
			cursor = style.Render("> ")
			cursorW = lipgloss.Width(cursor)
		}
		lineContent := cursor + style.Render(item)
		line := lipgloss.PlaceHorizontal(maxText+cursorW, lipgloss.Center, lineContent)
		lines = append(lines, line)
		if item == "Cache Options" {
			cacheIndex = len(lines) - 1
		}
	}
	return lines, cacheIndex
}

func renderMenuBlock(width int, menuBlock, noticeLine, helpText string) string {
	// center the constructed block and append notice/help text just like the original helper
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
	// animate and build the cache submenu block the same way as the previous implementation.
	maxCache := 0
	for _, item := range cache.Items {
		if w := lipgloss.Width(item); w > maxCache {
			maxCache = w
		}
	}
	innerWidth := maxCache + 4
	targetHeight := len(cache.Items) + 2
	delta := frame - cache.OpenFrame
	if delta < 0 {
		delta = 0
	}
	heightAnim := min(targetHeight, (delta+1)*3)
	if heightAnim < 1 {
		heightAnim = 1
	}

	progress := float64(delta) / float64(targetHeight)
	if progress > 1 {
		progress = 1
	}
	col := theme.BlendHex("#7D5FFF", "#F785D1", progress)
	if heightAnim >= targetHeight {
		col = "#8B5EDB"
	}
	boxStyle := lipgloss.NewStyle().Foreground(lipgloss.Color(col))

	var rows []string
	if heightAnim >= targetHeight {
		rows = append(rows, boxStyle.Render("   ╭"+strings.Repeat("─", innerWidth)+"╮"))
		for j, subItem := range cache.Items {
			sStyle := styles.VeryLightGray
			sCursor := "  "
			if j == cache.Selected {
				sStyle = styles.MenuSelected
				sCursor = styles.MenuSelected.Render("» ")
			}
			sLine := sCursor + sStyle.Render(subItem)
			padded := sLine
			if pad := innerWidth - lipgloss.Width(sLine); pad > 0 {
				padded += strings.Repeat(" ", pad)
			}
			leftBar := boxStyle.Render("   │")
			rightBar := boxStyle.Render("│")
			rows = append(rows, leftBar+padded+rightBar)
		}
		rows = append(rows, boxStyle.Render("   ╰"+strings.Repeat("─", innerWidth)+"╯"))
	} else {
		rows = append(rows, boxStyle.Render("   ╭"+strings.Repeat("─", innerWidth)+"╮"))
		mid := heightAnim - 1
		if mid < 0 {
			mid = 0
		}
		for k := 0; k < mid; k++ {
			leftBar := boxStyle.Render("   │")
			rightBar := boxStyle.Render("│")
			rows = append(rows, leftBar+strings.Repeat(" ", innerWidth)+rightBar)
		}
	}

	return strings.Join(rows, "\n")
}

func insertAfter(lines []string, idx int, block string) []string {
	if idx < 0 || idx >= len(lines) {
		return append(lines, block)
	}
	result := append([]string{}, lines[:idx+1]...)
	result = append(result, block)
	result = append(result, lines[idx+1:]...)
	return result
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
