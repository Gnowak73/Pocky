// Package ui starts the tui for pocky through bubble tea components in core
package ui

import (
	"fmt"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/chrome"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/core"
)

func Run() error {
	// First, the logo needs to be loaded pre model creation and and config
	// needs to be loaded. Type error is an interface with a method to print
	// the human readable error string.

	logo, err := chrome.LoadLogo()
	if err != nil {
		return fmt.Errorf("pocky logo: %w", err)
	}
	cfg := config.Load()

	// return an error if the TUI doesnt load and create a new
	// tea.Program after initializing a new model with default states.

	m := core.NewModel(logo, cfg)
	p := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseAllMotion())
	if _, err := p.Run(); err != nil {
		return fmt.Errorf("tui error: %w", err)
	}

	return nil
}
