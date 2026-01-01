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
	"github.com/pocky/tui-go/internal/tui/utils"
)

type FlaresLoadedMsg struct {
	Entries []Entry // slice of flare entries
	Header  string  // the raw header line from the flares data source. Used to preserve exact header when writing.
	Err     error   // error for python crashes
}

func LoadFlaresCmd(cfg config.Config) tea.Cmd {
	// given the config, we need an async (runs outside of main update loop) bubble tea command
	// that runs the external leader, parses its output into entries/header, and returns a FlaresLoadedMsg
	// so the model can update once loading finishes.

	return func() tea.Msg { // instantly gets called (no time scheduling)

		cmp := cfg.Comparator
		flareClass := cfg.FlareClass
		tmp, err := os.CreateTemp("", "pocky_flares_*.tsv")
		if err != nil {
			return FlaresLoadedMsg{Err: err}
		}
		// after making the tempfile, we close the open file description (the hander) for the temp file.
		// This is usually a small integer managed by the OS that indexes an internal table of open files.
		// The file stays on disk until we remove it. But our goal is to get the path, we don't need to have
		// it open for read/write.
		if err := tmp.Close(); err != nil {
			return FlaresLoadedMsg{Err: err}
		}

		// we only want the temp path. After we get the output of the python script,
		// we will put it into the temp file and read from it. Thus, we close the tmp handle and move on.
		// Also prevents us from having it open to read/write while python is writing to it to, don't want
		// a read/write lock problem.
		tmpPath := tmp.Name()
		defer func() {
			_ = os.Remove(tmpPath)
		}()

		// we do the python command (make a symlink or shim so "python" command works)
		cmd := exec.Command(
			"python",
			"query.py", cfg.Start, cfg.End, cmp, flareClass, cfg.Wave, tmpPath,
		)
		cmd.Dir = ".." // script directory is in /Pocky, one outside of /TUI-go
		if output, err := cmd.CombinedOutput(); err != nil {
			msg := strings.TrimSpace(string(output))
			return FlaresLoadedMsg{Err: fmt.Errorf("flare listing failed: %v (%s)", err, msg)}
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

	var b strings.Builder

	seen := make(map[string]struct{})
	writeLine := func(line string) {
		if _, ok := seen[line]; ok {
			return
		}
		seen[line] = struct{}{}
		fmt.Fprintln(&b, line)
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

	return utils.AtomicSave(cachePath, "flare_cache_*.tmp", []byte(b.String()), 0o600)
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
