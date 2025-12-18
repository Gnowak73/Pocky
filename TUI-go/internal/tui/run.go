package ui

import (
	"fmt"

	"github.com/pocky/tui-go/internal/tui/chrome"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/core"
)

func Run() error {
	logo, err := chrome.LoadLogo()
	if err != nil {
		return fmt.Errorf("pocky logo: %w", err)
	}

	cfg := config.Load()
	return core.Run(cfg, logo)
}
