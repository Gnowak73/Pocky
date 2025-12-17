package main

import (
	"fmt"
	"os"

	"github.com/pocky/tui-go/internal/ui"
)

func main() {
	if err := ui.Run(); err != nil {
		fmt.Println("tui error:", err)
		os.Exit(1)
	}
}
