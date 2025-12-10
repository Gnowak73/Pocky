package main

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
			cfg.Wave = val
		case "START":
			cfg.Start = val
		case "END":
			cfg.End = val
		case "SOURCE":
			cfg.Source = val
		case "FLARE_CLASS":
			cfg.FlareClass = val
		case "COMPARATOR":
			cfg.Comparator = val
		case "DL_EMAIL":
			cfg.Dlemail = val
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
	fmt.Fprintf(&b, "WAVE=\"%s\"\n", cfg.Wave)
	fmt.Fprintf(&b, "START=\"%s\"\n", cfg.Start)
	fmt.Fprintf(&b, "END=\"%s\"\n", cfg.End)
	fmt.Fprintf(&b, "SOURCE=\"%s\"\n", cfg.Source)
	fmt.Fprintf(&b, "FLARE_CLASS=\"%s\"\n", cfg.FlareClass)
	fmt.Fprintf(&b, "COMPARATOR=\"%s\"\n", cfg.Comparator)
	fmt.Fprintf(&b, "DL_EMAIL=\"%s\"\n", cfg.Dlemail)

	tmp := target + ".tmp"
	if err := os.WriteFile(tmp, []byte(b.String()), 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, target)
}
