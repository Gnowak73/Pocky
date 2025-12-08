package main

import (
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"
)

func main() {
	// logo.go
	logo, err := loadLogo()
	if err != nil {
		fmt.Println("pocky logo:", err)
		os.Exit(1)
	}

	cfg := loadConfig()
	m := newModel(logo, cfg)
	if err := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseAllMotion()).Start(); err != nil {
		fmt.Println("tui error:", err)
		os.Exit(1)
	}
}
