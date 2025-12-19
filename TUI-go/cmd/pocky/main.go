package main

import (
	"fmt"
	"os"

	ui "github.com/pocky/tui-go/internal/tui"
)

func main() {
	// function ui returns an error, which we check upon running to start
	// bubble tea model
	if err := ui.Run(); err != nil {
		fmt.Println("tui error:", err)
		os.Exit(1)
	}
}
