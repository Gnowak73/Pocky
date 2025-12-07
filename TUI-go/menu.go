package main

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
)

func renderMenu(m model, width int) string {
	if m.mode != modeMain {
		return ""
	}
	var lines []string
	maxText := 0
	for _, item := range m.menuItems {
		if w := lipgloss.Width(item); w > maxText {
			maxText = w
		}
	}
	noticeLine := ""
	if nl := m.noticeLine(width); nl != "" {
		noticeLine = nl
	}
	for i, item := range m.menuItems {
		style := menuItemStyle
		cursor := "  "
		cursorW := lipgloss.Width(cursor)
		if i == m.selected {
			style = menuSelectedStyle
			cursor = lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1")).Render("> ")
			cursorW = lipgloss.Width(cursor)
		}
		lineContent := cursor + style.Render(item)
		line := lipgloss.PlaceHorizontal(maxText+cursorW, lipgloss.Center, lineContent)
		lines = append(lines, line)
	}

	menuBlock := strings.Join(lines, "\n")

	helpText := "↑/k up • ↓/j down • enter submit"

	if width <= 0 {
		help := menuHelpStyle.Render(helpText)
		if noticeLine != "" {
			return "\n\n" + menuBlock + "\n\n" + "  " + noticeLine + "\n\n" + help
		}
		return "\n\n" + menuBlock + "\n\n" + help
	}

	placed := lipgloss.Place(width, lipgloss.Height(menuBlock), lipgloss.Center, lipgloss.Top, menuBlock)
	help := lipgloss.Place(width, 1, lipgloss.Center, lipgloss.Top, menuHelpStyle.Render(helpText))
	var shifted []string
	for _, line := range strings.Split(placed, "\n") {
		if strings.HasPrefix(line, " ") {
			line = line[1:]
		}
		shifted = append(shifted, line)
	}
	block := "\n\n" + strings.Join(shifted, "\n")
	if noticeLine != "" {
		block += "\n\n" + noticeLine
	}
	return block + "\n\n" + help
}

// renderMenuWithCache shows the main menu with an inline submenu under Cache Options.
func renderMenuWithCache(m model, width int) string {
	var lines []string
	maxText := 0
	for _, item := range m.menuItems {
		if w := lipgloss.Width(item); w > maxText {
			maxText = w
		}
	}
	noticeLine := ""
	if nl := m.noticeLine(width); nl != "" {
		noticeLine = nl
	}

	for i, item := range m.menuItems {
		style := menuItemStyle
		cursor := "  "
		cursorW := lipgloss.Width(cursor)
		if i == m.selected {
			style = menuSelectedStyle
			cursor = lipgloss.NewStyle().Foreground(lipgloss.Color("#F785D1")).Render("> ")
			cursorW = lipgloss.Width(cursor)
		}
		lineContent := cursor + style.Render(item)
		line := lipgloss.PlaceHorizontal(maxText+cursorW, lipgloss.Center, lineContent)
		lines = append(lines, line)

		if item == "Cache Options" && m.cacheMenuOpen {
			maxCache := 0
			for _, it := range m.cacheMenuItems {
				if w := lipgloss.Width(it); w > maxCache {
					maxCache = w
				}
			}
			innerWidth := maxCache + 4
			targetHeight := len(m.cacheMenuItems) + 2
			delta := m.frame - m.cacheOpenFrame
			if delta < 0 {
				delta = 0
			}
			heightAnim := minInt(targetHeight, (delta+1)*3)
			if heightAnim < 1 {
				heightAnim = 1
			}

			progress := float64(delta) / float64(targetHeight)
			if progress > 1 {
				progress = 1
			}
			col := blendHex("#7D5FFF", "#F785D1", progress)
			if heightAnim >= targetHeight {
				col = "#8B5EDB"
			}
			boxStyle := lipgloss.NewStyle().Foreground(lipgloss.Color(col))

			if heightAnim >= targetHeight {
				var sub []string
				top := boxStyle.Render("   ╭" + strings.Repeat("─", innerWidth) + "╮")
				sub = append(sub, top)
				for j, subItem := range m.cacheMenuItems {
					sStyle := menuItemStyle.Copy().Foreground(lipgloss.Color("252"))
					sCursor := "  "
					if j == m.cacheSelected {
						sStyle = menuSelectedStyle
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
	help := menuHelpStyle.Render(helpText)
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

func (m model) menuIndexAt(x, y int) (int, bool) {
	if y < 0 || x < 0 || len(m.menuItems) == 0 {
		return 0, false
	}

	if m.mode != modeMain {
		return 0, false
	}

	content := strings.Join(m.colored, "\n")
	boxContent := logoBoxStyle.Render(content)

	w := m.width
	if w <= 0 {
		w = lipgloss.Width(boxContent)
	}
	box := lipgloss.Place(w, lipgloss.Height(boxContent), lipgloss.Center, lipgloss.Top, boxContent)

	boxWidth := lipgloss.Width(boxContent)
	versionText := versionStyle.Render("VERSION: 0.2")
	leftPad := 0
	if w > boxWidth {
		leftPad = (w - boxWidth) / 2
	}
	versionLine := strings.Repeat(" ", leftPad) + lipgloss.Place(boxWidth, 1, lipgloss.Right, lipgloss.Top, versionText)

	summary := renderSummary(m.cfg, w)
	menu := renderMenu(m, w)

	header := box + "\n" + versionLine + summary
	menuTop := lipgloss.Height(header)
	menuHeight := lipgloss.Height(menu)
	if y < menuTop || y >= menuTop+menuHeight {
		return 0, false
	}

	relativeY := y - menuTop
	start := 1
	itemY := relativeY - start
	if itemY < 0 || itemY >= len(m.menuItems) {
		return 0, false
	}

	return itemY, true
}

// cacheMenuIndexAt maps mouse coords to a cache submenu item when open.
func (m model) cacheMenuIndexAt(x, y int) (int, bool) {
	if !m.cacheMenuOpen || m.mode != modeMain {
		return 0, false
	}

	content := strings.Join(m.colored, "\n")
	boxContent := logoBoxStyle.Render(content)

	w := m.width
	if w <= 0 {
		w = lipgloss.Width(boxContent)
	}
	box := lipgloss.Place(w, lipgloss.Height(boxContent), lipgloss.Center, lipgloss.Top, boxContent)

	boxWidth := lipgloss.Width(boxContent)
	versionText := versionStyle.Render("VERSION: 0.2")
	leftPad := 0
	if w > boxWidth {
		leftPad = (w - boxWidth) / 2
	}
	versionLine := strings.Repeat(" ", leftPad) + lipgloss.Place(boxWidth, 1, lipgloss.Right, lipgloss.Top, versionText)

	summary := renderSummary(m.cfg, w)
	header := box + "\n" + versionLine + summary
	menuTop := maxInt(lipgloss.Height(header)+1, 0)

	var lines []string
	maxText := 0
	for _, item := range m.menuItems {
		if val := lipgloss.Width(item); val > maxText {
			maxText = val
		}
	}

	cacheOptLine := -1
	for _, item := range m.menuItems {
		cursor := "  "
		cursorW := lipgloss.Width(cursor)
		lineContent := cursor + menuItemStyle.Render(item)
		line := lipgloss.PlaceHorizontal(maxText+cursorW, lipgloss.Center, lineContent)
		lines = append(lines, line)
		if item == "Cache Options" {
			cacheOptLine = len(lines) - 1
			maxCache := 0
			for _, it := range m.cacheMenuItems {
				if w := lipgloss.Width(it); w > maxCache {
					maxCache = w
				}
			}
			innerWidth := maxCache + 4
			lines = append(lines, "   ╭"+strings.Repeat("─", innerWidth)+"╮")
			for _, subItem := range m.cacheMenuItems {
				sLine := "  " + menuItemStyle.Render(subItem)
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
	if relativeY < itemStart || relativeY >= itemStart+len(m.cacheMenuItems) {
		return 0, false
	}
	idx := relativeY - itemStart
	if idx < 0 || idx >= len(m.cacheMenuItems) {
		return 0, false
	}
	return idx, true
}
