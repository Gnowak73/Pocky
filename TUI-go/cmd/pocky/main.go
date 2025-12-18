package main

import (
	"fmt"
	"os"

	ui "github.com/pocky/tui-go/internal/tui"
)

func main() {
	if err := ui.Run(); err != nil {
		fmt.Println("tui error:", err)
		os.Exit(1)
	}
}
