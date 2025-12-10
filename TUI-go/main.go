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

	// config doesnt need error check because if it doesn't
	// exist we will have env vars unset and save them later
	cfg := loadConfig()

	// we will use the logo and config to initialize our model since
	// the main menu is build from config + logo + options as a basis
	m := newModel(logo, cfg)

	// bubbletea will immediate call Init(), then go into a loop of
	// Update() -> View() for the duration of the program,
	// it will render only when an update is being put through tea.Msg(),
	// else it stays static
	p := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseAllMotion())
	if _, err := p.Run(); err != nil {
		// for now we don't care about final state, just the error
		fmt.Println("tui error:", err)
		os.Exit(1)
	}
}
