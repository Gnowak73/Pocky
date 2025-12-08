package main

import (
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"
)

func main() {
	// do the logo and config exist?
	// If yes, read. If no, error

	logo, err := loadLogo()
	if err != nil {
		fmt.Println("pocky logo:", err)
		os.Exit(1)
	}

	// for now we don't care about final state, just the error
	cfg := loadConfig()
	m := newModel(logo, cfg)
	p := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseAllMotion())
	if _, err := p.Run(); err != nil {
		fmt.Println("tui error:", err)
		os.Exit(1)
	}
}
