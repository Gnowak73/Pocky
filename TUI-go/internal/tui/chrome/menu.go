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
	OpenFrame int // the frame counter captures when the submenu is opened for wire box expansion
}

func RenderMenu(width int, menu MenuState, noticeLine string) string {
	// the goal is to return a string to print to the TUI, reflecting the state of the
	// main menu. We will need a separate function for the cache submenu since it has
	// its own different animation going on and a change in the layout of the window.

	// since lines may be of different width, we must create a buffer slice to hold the
	// styled lines, which are separated centered and positioned, before putting them together
	// into one big block.
	var lines []string
	maxText := 0

	// we need to know the max width between all lines since centering the block will mean
	// we center the list of menu items as a whole but we also want each line to be centered too.
	// Thus, we use the maxText to
	for _, item := range menu.Items {
		maxText = max(lipgloss.Width(item), maxText)
	}

	for i, item := range menu.Items {
		style := styles.MenuItem

		// an extra space is to reserve the same space as the arrow "> " to keep padding
		// uniform so non selected items arent shifted to the left of the seelected one
		cursor := "  "
		if i == menu.Selected {
			style = styles.MenuSelected
			cursor = style.Render("> ") // Render is for standalone strings
		}
		lineContent := cursor + style.Render(item)

		// the width of the coursor is irrelevant since we only care about the centering of the
		// options themselves, not the empty space from the cursor
		line := lipgloss.PlaceHorizontal(maxText, lipgloss.Center, lineContent)
		lines = append(lines, line)
	}

	// now we construct the block and center the entire block of individual lines (which have their
	// own little window grid they are in)
	menuBlock := strings.Join(lines, "\n")
	helpText := "↑/k up • ↓/j down • enter submit"

	// menu is rendered first, so we keep a safeguard in case at launch the window size hasn't been reported yet
	// where we dont use lipgloss.Place. Rather, we just stack everything on the left-hand side.
	if width <= 0 {
		help := styles.LightGray.Render(helpText)
		if noticeLine != "" {
			return "\n\n" + menuBlock + "\n\n" + "  " + noticeLine + "\n\n" + help
		}
		return "\n\n" + menuBlock + "\n\n" + help
	}

	placed := lipgloss.Place(width-2, // descrease by cursor width for centered options
		lipgloss.Height(menuBlock),
		lipgloss.Center, lipgloss.Top,
		menuBlock,
	)

	help := lipgloss.Place(width,
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

func RenderMenuWithCache(width int, menu MenuState, cache CacheMenuView, frame int, noticeLine string) string {
	// we need to follow the same process, just add the additional cache options
	var lines []string
	maxText := 0
	for _, item := range menu.Items {
		if w := lipgloss.Width(item); w > maxText {
			maxText = w
		}
	}

	for i, item := range menu.Items {
		style := styles.MenuItem
		cursor := "  "
		cursorW := lipgloss.Width(cursor)
		if i == menu.Selected {
			style = styles.MenuSelected
			cursor = lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1")).Render("> ")
			cursorW = lipgloss.Width(cursor)
		}
		lineContent := cursor + style.Render(item)
		line := lipgloss.PlaceHorizontal(maxText+cursorW, lipgloss.Center, lineContent)
		lines = append(lines, line)

		if item == "Cache Options" && cache.Open {
			maxCache := 0
			for _, it := range cache.Items {
				if w := lipgloss.Width(it); w > maxCache {
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

			if heightAnim >= targetHeight {
				var sub []string
				top := boxStyle.Render("   ╭" + strings.Repeat("─", innerWidth) + "╮")
				sub = append(sub, top)
				for j, subItem := range cache.Items {
					sStyle := styles.VeryLightGray
					sCursor := "  "
					if j == cache.Selected {
						sStyle = styles.MenuSelected
						sCursor = lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1")).Render("» ")
					}
					sLine := sCursor + sStyle.Render(subItem)
					padded := sLine
					if pad := innerWidth - lipgloss.Width(sLine); pad > 0 {
						padded += strings.Repeat(" ", pad)
					}
					leftBar := boxStyle.Render("   │")
					rightBar := boxStyle.Render("│")
					sub = append(sub, leftBar+padded+rightBar)
				}
				bottom := boxStyle.Render("   ╰" + strings.Repeat("─", innerWidth) + "╯")
				sub = append(sub, bottom)
				lines = append(lines, strings.Join(sub, "\n"))
			} else {
				var partial []string
				partial = append(partial, boxStyle.Render("   ╭"+strings.Repeat("─", innerWidth)+"╮"))
				mid := heightAnim - 1
				if mid < 0 {
					mid = 0
				}
				for k := 0; k < mid; k++ {
					leftBar := boxStyle.Render("   │")
					rightBar := boxStyle.Render("│")
					partial = append(partial, leftBar+strings.Repeat(" ", innerWidth)+rightBar)
				}
				lines = append(lines, strings.Join(partial, "\n"))
			}
		}
	}

	mainBlock := strings.Join(lines, "\n")
	helpText := "↑/k up • ↓/j down • enter submit • esc close cache"
	help := styles.LightGray.Render(helpText)
	joined := mainBlock

	if width <= 0 {
		block := "\n\n" + joined
		if noticeLine != "" {
			block += "\n\n" + noticeLine
		}
		return block + "\n\n" + help
	}

	placed := lipgloss.Place(width, lipgloss.Height(joined), lipgloss.Center, lipgloss.Top, joined)
	helpLine := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, help)
	block := "\n\n" + placed
	if noticeLine != "" {
		block += "\n\n" + noticeLine
	}
	return block + "\n\n" + helpLine
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
	menuView := RenderMenu(w, menu, "")

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
