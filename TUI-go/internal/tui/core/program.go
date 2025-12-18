package core

import (
	"fmt"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/config"
)

func Run(cfg config.Config, logoLines []string) error {
	m := NewModel(logoLines, cfg)
	p := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseAllMotion())
	if _, err := p.Run(); err != nil {
		return fmt.Errorf("tui error: %w", err)
	}
	return nil
}
