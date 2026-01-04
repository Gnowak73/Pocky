package core

import (
	tea "github.com/charmbracelet/bubbletea"
)

func (m Model) handleKeyMsg(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch m.Mode {
	case ModeMain:
		return m.handleMainKeys(msg)
	case ModeCacheView:
		return m.handleCacheViewKeys(msg)
	case ModeCacheDelete:
		return m.handleCacheDeleteKeys(msg)
	case ModeWavelength:
		return m.handleWavelengthKeys(msg)
	case ModeDateRange:
		return m.handleDateKeys(msg)
	case ModeFlareFilter:
		return m.handleFlareFilterKeys(msg)
	case ModeSelectFlares:
		return m.handleSelectFlaresKeys(msg)
	case ModeDownloadMenu:
		return m.handleDownloadMenuKeys(msg)
	case ModeDownloadForm:
		return m.handleDownloadFormKeys(msg)
	case ModeDownloadRun:
		return m, nil
	default:
		return m, nil
	}
}

func (m Model) handleMouseMsg(msg tea.MouseMsg) (tea.Model, tea.Cmd) {
	switch m.Mode {
	case ModeMain:
		return m.handleMainMouse(msg)
	case ModeCacheView:
		var cmd tea.Cmd
		m.Cache.Viewport, cmd = m.Cache.Viewport.Update(msg)
		return m, cmd
	case ModeCacheDelete:
		return m.handleCacheDeleteMouse(msg)
	case ModeWavelength:
		return m.handleWavelengthMouse(msg)
	case ModeFlareFilter:
		return m.handleFlareFilterMouse(msg)
	case ModeSelectFlares:
		return m.handleSelectFlaresMouse(msg)
	case ModeDownloadMenu:
		return m.handleDownloadMenuMouse(msg)
	case ModeDownloadRun:
		return m, nil
	default:
		return m, nil
	}
}
