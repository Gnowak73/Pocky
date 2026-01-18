package flares

import (
	"bufio"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

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

		// after getting the output into the temp file, we reopen it to get the results
		f, err := os.Open(tmpPath)
		if err != nil {
			return FlaresLoadedMsg{Err: err}
		}

		defer func() {
			if err := f.Close(); err != nil {
				// default prints to terminal:
				log.Printf("close flare temp: %v", err)
			}
		}()

		// we would like to read the file line by line and record the entries from each line as an []Entry.
		// We naturally use scanners, which reads input and splits it into tokens (lines by default)
		scanner := bufio.NewScanner(f)
		if !scanner.Scan() { // .Scan() advances to the next line, returning a boolean if it read a line or not
			return FlaresLoadedMsg{Err: fmt.Errorf("empty flare listing")}
		}
		header := scanner.Text() // first line scan and extract text
		var entries []Entry

		// we go through ecah following line after the header and collect the info
		for scanner.Scan() {
			line := scanner.Text()
			fields := strings.Split(line, "\t")
			if len(fields) < 6 { // we only want full data lines
				continue
			}
			// we would like the times to be in human readable format and not TZ
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
		// the header is returned to be saved for later in the SaveFlareSelection()
		return FlaresLoadedMsg{Entries: entries, Header: header}
	}
}

func SaveFlareSelection(entries []Entry, selected map[int]bool, header string) error {
	// we take the parts of FlaresLoadedMsg and input them into this function to save the
	// current flare entires into flare_cache.tsv
	if len(selected) == 0 {
		return nil
	}

	// the keys of the selected map are recorded as the index with respect to the
	// Selector.List []Entry slice, hence the int. The value is boolean:
	// whether or not we are selecting that entry.

	var chosen []string // the raw tsv lines that will be saves
	for idx := range selected {
		if idx >= 0 && idx < len(entries) {
			// we will keep the full raw data from the python script. We will use
			// the tab data for the selection UI, but we would like the raw data to preserve
			// formatting, or have lossless output
			chosen = append(chosen, entries[idx].Full)
		}
	}
	if len(chosen) == 0 {
		return nil
	}

	cachePath := filepath.Join("..", "flare_cache.tsv")
	var existingHeader string
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
		existingHeader = strings.TrimSpace(header)
	}
	if strings.TrimSpace(existingHeader) == "" {
		return fmt.Errorf("flare_cache.tsv missing header")
	}

	// we would like a way to build string without repeated allocations. Hence, we need
	// a builder. We need to track which lines we have already seen. To do this, we will have a map
	// from a string (the line in question) to an empty struct. The empty struct{} takes up no memory
	// but if there is a key exists, an if statement will return a boolean. So we dont really need a
	// value to check if it's been seen.
	var b strings.Builder
	seen := make(map[string]struct{})
	writeLine := func(line string) {
		if _, ok := seen[line]; ok {
			return
		}
		seen[line] = struct{}{}
		fmt.Fprintln(&b, line)
	}

	// we now write the current existing lines back into the string builder along with the chosen new
	// lines that were not there. Because we check with writeLine if we saw an input or not, we don't
	// duplicate old and new lines that overlap.
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
