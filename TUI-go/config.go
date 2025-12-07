package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

func loadConfig() config {
	paths := []string{
		".vars.env",
		filepath.Join("..", ".vars.env"),
	}

	var cfg config
	for _, p := range paths {
		data, err := os.ReadFile(p)
		if err != nil {
			continue
		}
		lines := strings.Split(string(data), "\n")
		for _, line := range lines {
			line = strings.TrimSpace(line)
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			parts := strings.SplitN(line, "=", 2)
			if len(parts) != 2 {
				continue
			}
			key := parts[0]
			val := strings.Trim(parts[1], "\"")
			switch key {
			case "WAVE":
				cfg.WAVE = val
			case "START":
				cfg.START = val
			case "END":
				cfg.END = val
			case "SOURCE":
				cfg.SOURCE = val
			case "FLARE_CLASS":
				cfg.FLARE_CLASS = val
			case "COMPARATOR":
				cfg.COMPARATOR = val
			case "DL_EMAIL":
				cfg.DL_EMAIL = val
			}
		}
		break
	}
	return cfg
}

func saveConfig(cfg config) error {
	paths := []string{
		".vars.env",
		filepath.Join("..", ".vars.env"),
	}

	target := paths[0]
	for _, p := range paths {
		if _, err := os.Stat(p); err == nil {
			target = p
			break
		}
	}

	var b strings.Builder
	fmt.Fprintf(&b, "WAVE=\"%s\"\n", cfg.WAVE)
	fmt.Fprintf(&b, "START=\"%s\"\n", cfg.START)
	fmt.Fprintf(&b, "END=\"%s\"\n", cfg.END)
	fmt.Fprintf(&b, "SOURCE=\"%s\"\n", cfg.SOURCE)
	fmt.Fprintf(&b, "FLARE_CLASS=\"%s\"\n", cfg.FLARE_CLASS)
	fmt.Fprintf(&b, "COMPARATOR=\"%s\"\n", cfg.COMPARATOR)
	fmt.Fprintf(&b, "DL_EMAIL=\"%s\"\n", cfg.DL_EMAIL)

	tmp := target + ".tmp"
	if err := os.WriteFile(tmp, []byte(b.String()), 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, target)
}
