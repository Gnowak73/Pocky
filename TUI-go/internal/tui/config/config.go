// Package config is just to load and save the current settings of the user in the TUI,
// we also supply the ParentDirFile
package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type Config struct {
	Wave       string
	Start      string
	End        string
	Source     string
	FlareClass string
	Comparator string
	DLEmail    string
}

// ParentDirFile returns a path that lives in the parent directory of the
// running executable. It is used to find shared assets like .vars.env or
// logo.txt when the binary is invoked from the cmd/ directory.
func ParentDirFile(filename string) string {
	var parent string
	if exe, err := os.Executable(); err == nil {
		exeDir := filepath.Dir(exe)
		parent = filepath.Dir(exeDir)
		return filepath.Join(parent, filename)
	}
	return ""
}

func Load() Config {
	// we need to see if the config file is
	// in the parent directory for the ui model
	// no global var for path used since its infrequent
	path := ParentDirFile(".vars.env")
	data, _ := os.ReadFile(path)
	var cfg Config

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
			cfg.DLEmail = val
		}
	}
	return cfg
}

func Save(cfg Config) error {
	target := ParentDirFile(".vars.env")

	var b strings.Builder
	fmt.Fprintf(&b, "WAVE=\"%s\"\n", cfg.Wave)
	fmt.Fprintf(&b, "START=\"%s\"\n", cfg.Start)
	fmt.Fprintf(&b, "END=\"%s\"\n", cfg.End)
	fmt.Fprintf(&b, "SOURCE=\"%s\"\n", cfg.Source)
	fmt.Fprintf(&b, "FLARE_CLASS=\"%s\"\n", cfg.FlareClass)
	fmt.Fprintf(&b, "COMPARATOR=\"%s\"\n", cfg.Comparator)
	fmt.Fprintf(&b, "DL_EMAIL=\"%s\"\n", cfg.DLEmail)

	tmp := target + ".tmp"
	if err := os.WriteFile(tmp, []byte(b.String()), 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, target)
}
