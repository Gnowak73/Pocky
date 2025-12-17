package ui

import (
	"fmt"
	"os"
	"strings"
)

func loadConfig() config {
	// we need to see if the config file is
	// in the parent directory for the ui model
	// no global var for path used since its infrequent

	path := parentDirFile(".vars.env")
	data, _ := os.ReadFile(path)
	var cfg config

	// we need to search through the config to set env vars
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
			cfg.wave = val
		case "START":
			cfg.start = val
		case "END":
			cfg.end = val
		case "SOURCE":
			cfg.source = val
		case "FLARE_CLASS":
			cfg.flareClass = val
		case "COMPARATOR":
			cfg.comparator = val
		case "DL_EMAIL":
			cfg.dlEmail = val
		}
	}
	return cfg
}

func saveConfig(cfg config) error {
	// we need to save the config where it should be
	// To prevents errors from crashing while saving, we will use
	// a tmp file with os.rename which is atomic (all or nothing)
	target := parentDirFile(".vars.env")

	var b strings.Builder
	fmt.Fprintf(&b, "WAVE=\"%s\"\n", cfg.wave)
	fmt.Fprintf(&b, "START=\"%s\"\n", cfg.start)
	fmt.Fprintf(&b, "END=\"%s\"\n", cfg.end)
	fmt.Fprintf(&b, "SOURCE=\"%s\"\n", cfg.source)
	fmt.Fprintf(&b, "FLARE_CLASS=\"%s\"\n", cfg.flareClass)
	fmt.Fprintf(&b, "COMPARATOR=\"%s\"\n", cfg.comparator)
	fmt.Fprintf(&b, "DL_EMAIL=\"%s\"\n", cfg.dlEmail)

	tmp := target + ".tmp"
	if err := os.WriteFile(tmp, []byte(b.String()), 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, target)
}
