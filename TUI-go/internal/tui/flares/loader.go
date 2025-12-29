package flares

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/config"
)

type FlaresLoadedMsg struct {
	Entries []Entry
	Header  string
	Err     error
}

func LoadFlaresCmd(cfg config.Config) tea.Cmd {
	return func() tea.Msg {
		cmp := ComparatorASCII(cfg.Comparator)
		if strings.TrimSpace(cfg.Start) == "" || strings.TrimSpace(cfg.End) == "" || strings.TrimSpace(cfg.Wave) == "" || cmp == "" {
			return FlaresLoadedMsg{Err: fmt.Errorf("missing required fields")}
		}

		flareClass := cfg.FlareClass
		if strings.TrimSpace(flareClass) == "" {
			flareClass = "A0.0"
		}

		tmp, err := os.CreateTemp("", "pocky_flares_*.tsv")
		if err != nil {
			return FlaresLoadedMsg{Err: err}
		}
		tmp.Close()
		tmpPath := tmp.Name()
		defer func() {
			_ = os.Remove(tmpPath)
		}()

		cmd := exec.Command("python", "query.py", cfg.Start, cfg.End, cmp, flareClass, cfg.Wave, tmpPath)
		cmd.Dir = ".."
		if output, err := cmd.CombinedOutput(); err != nil {
			return FlaresLoadedMsg{Err: fmt.Errorf("flare listing failed: %v (%s)", err, strings.TrimSpace(string(output)))}
		}

		f, err := os.Open(tmpPath)
		if err != nil {
			return FlaresLoadedMsg{Err: err}
		}
		defer f.Close()

		scanner := bufio.NewScanner(f)
		if !scanner.Scan() {
			return FlaresLoadedMsg{Err: fmt.Errorf("empty flare listing")}
		}
		header := scanner.Text()
		var entries []Entry
		for scanner.Scan() {
			line := scanner.Text()
			fields := strings.Split(line, "\t")
			if len(fields) < 6 {
				continue
			}
			startHuman := isoToHuman(fields[2])
			endHuman := isoToHuman(fields[3])
			if endHuman == "" {
				endHuman = startHuman
			}
			entries = append(entries, Entry{
				Desc:  fields[0],
				Class: fields[1],
				Start: startHuman,
				End:   endHuman,
				Coord: fields[4],
				Full:  line,
			})
		}
		if err := scanner.Err(); err != nil {
			return FlaresLoadedMsg{Err: err}
		}
		return FlaresLoadedMsg{Entries: entries, Header: header}
	}
}

func SaveFlareSelection(header string, entries []Entry, selected map[int]bool) error {
	if len(selected) == 0 {
		return nil
	}
	var chosen []string
	for idx := range selected {
		if idx >= 0 && idx < len(entries) {
			chosen = append(chosen, entries[idx].Full)
		}
	}
	if len(chosen) == 0 {
		return nil
	}

	cachePath := filepath.Join("..", "flare_cache.tsv")
	existingHeader := header
	var existing []string
	if data, err := os.ReadFile(cachePath); err == nil {
		lines := strings.Split(strings.TrimRight(string(data), "\n"), "\n")
		if len(lines) > 0 {
			existingHeader = lines[0]
			if len(lines) > 1 {
				existing = lines[1:]
			}
		}
	}
	if strings.TrimSpace(existingHeader) == "" {
		existingHeader = "description\tflare_class\tstart\tend\tcoordinates\twavelength"
	}

	tmp, err := os.CreateTemp(filepath.Dir(cachePath), "flare_cache_*.tmp")
	if err != nil {
		return err
	}
	tmpPath := tmp.Name()
	defer func() {
		_ = os.Remove(tmpPath)
	}()
	out := tmp

	seen := make(map[string]struct{})
	writeLine := func(line string) {
		if _, ok := seen[line]; ok {
			return
		}
		seen[line] = struct{}{}
		fmt.Fprintln(out, line)
	}

	writeLine(existingHeader)
	for _, line := range existing {
		if strings.TrimSpace(line) != "" {
			writeLine(line)
		}
	}
	for _, line := range chosen {
		if strings.TrimSpace(line) != "" {
			writeLine(line)
		}
	}

	if err := out.Close(); err != nil {
		return err
	}
	return os.Rename(tmpPath, cachePath)
}

func isoToHuman(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return ""
	}
	s = strings.TrimSuffix(s, "Z")
	s = strings.ReplaceAll(s, "T", " ")
	if idx := strings.IndexRune(s, '.'); idx >= 0 {
		s = s[:idx]
	}
	return s
}

func ValidDate(val string) bool {
	val = strings.TrimSpace(val)
	if val == "" {
		return false
	}
	if len(val) != len("2006-01-02") {
		return false
	}
	_, err := time.Parse("2006-01-02", val)
	return err == nil
}

func Chronological(start, end string) bool {
	s, err1 := time.Parse("2006-01-02", start)
	e, err2 := time.Parse("2006-01-02", end)
	if err1 != nil || err2 != nil {
		return false
	}
	return !s.After(e)
}
