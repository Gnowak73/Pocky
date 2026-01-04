package downloads

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/config"
)

type DownloadFinishedMsg struct {
	Output   string // this will be the output from the python file just like in query.py
	Email    string // last JSOC email used for downloads
	Canceled bool
	Err      error
}

type DownloadStartedMsg struct {
	OutputCh <-chan string
	DoneCh   <-chan DownloadFinishedMsg
	Cancel   context.CancelFunc
}

type DownloadOutputMsg struct {
	Line string
}

func ListenDownloadCmd(outputCh <-chan string, doneCh <-chan DownloadFinishedMsg) tea.Cmd {
	// keep the loop alive by blocking for a single output or completion message,
	// then returning it back to the update loop.
	return func() tea.Msg {
		if outputCh == nil || doneCh == nil {
			return nil
		}
		select {
		case line, ok := <-outputCh:
			if ok {
				return DownloadOutputMsg{Line: line}
			}
			msg, ok := <-doneCh
			if ok {
				return msg
			}
			return nil
		case msg := <-doneCh:
			return msg
		}
	}
}

func RunDownloadCmd(state DownloadState, cfg config.Config) tea.Cmd {
	// we run the download asynchronously so the TUI stays responsive; this mirrors the
	// loader.go pattern where python runs outside the main update loop and returns a msg.
	return func() tea.Msg {
		// fall back to the shared assets in the parent directory of the running binary,
		// same pattern as config.ParentDirFile in loader and config handling.
		tsv := strings.TrimSpace(state.Form.TSVPath)
		if tsv == "" {
			tsv = config.ParentDirFile("flare_cache.tsv")
			if tsv == "" {
				tsv = "flare_cache.tsv"
			}
		}
		if _, err := os.Stat(tsv); err != nil {
			return DownloadFinishedMsg{
				Err: fmt.Errorf("flare_cache.tsv not found at %s", tsv),
			}
		}

		// resolve output directory by level with the same parent-dir fallback as the cache path.
		outDir := strings.TrimSpace(state.Form.OutDir)
		if outDir == "" {
			if state.Level == Level1p5 {
				outDir = config.ParentDirFile("data_aia_lvl1.5")
				if outDir == "" {
					outDir = "data_aia_lvl1.5"
				}
			} else {
				outDir = config.ParentDirFile("data_aia_lvl1")
				if outDir == "" {
					outDir = "data_aia_lvl1"
				}
			}
		}

		maxConn := strings.TrimSpace(state.Form.MaxConn)
		if maxConn == "" {
			maxConn = "6"
		}
		maxSplits := strings.TrimSpace(state.Form.MaxSplits)
		if maxSplits == "" {
			maxSplits = "3"
		}
		attempts := strings.TrimSpace(state.Form.Attempts)
		if attempts == "" {
			if state.Protocol == ProtocolFido {
				attempts = "3"
			} else {
				attempts = "5"
			}
		}
		cadence := strings.TrimSpace(state.Form.Cadence)
		if cadence == "" {
			if state.Protocol == ProtocolFido {
				cadence = "12"
			} else {
				cadence = "12s"
			}
		}
		if state.Protocol == ProtocolFido {
			cadence = strings.TrimSuffix(cadence, "s")
			cadence = strings.TrimSuffix(cadence, "S")
			if cadence == "" {
				cadence = "12"
			}
		} else if !strings.HasSuffix(cadence, "s") && !strings.HasSuffix(cadence, "S") {
			cadence += "s"
		}
		padBefore := strings.TrimSpace(state.Form.PadBefore)
		if padBefore == "" {
			padBefore = "0"
		}
		padAfter := strings.TrimSpace(state.Form.PadAfter)

		// use last saved email as a fallback to mirror the shell flow.
		email := strings.TrimSpace(state.Form.Email)
		if email == "" {
			email = strings.TrimSpace(cfg.DLEmail)
		}

		usedEmail := ""
		var cmd *exec.Cmd
		switch state.Protocol {
		case ProtocolDRMS:
			// DRMS always requires an email, and uses the series + optional pad-after.
			if email == "" {
				return DownloadFinishedMsg{Err: fmt.Errorf("JSOC email is required")}
			}
			args := []string{
				"fetch_jsoc_drms.py",
				"--tsv", tsv,
				"--out", outDir,
				"--max-conn", maxConn,
				"--max-splits", maxSplits,
				"--attempts", attempts,
				"--cadence", cadence,
				"--series", "aia.lev1_euv_12s",
				"--pad-before", padBefore,
			}
			if padAfter != "" {
				args = append(args, "--pad-after", padAfter)
			}
			if state.Level == Level1p5 {
				args = append(args, "--aia-scale")
			}
			args = append(args, "--email", email)
			usedEmail = email
			cmd = exec.Command("python", args...)

		case ProtocolFido:
			provider := strings.TrimSpace(string(state.Form.Provider))
			if provider == "" {
				provider = "vso"
			}
			if provider == "jsoc" && email == "" {
				return DownloadFinishedMsg{Err: fmt.Errorf("JSOC email is required")}
			}

			// Fido uses a different script and cadence units (seconds vs 12s).
			args := []string{
				"fetch_fido.py",
				"--tsv", tsv,
				"--out", outDir,
				"--cadence", cadence,
				"--pad-before", padBefore,
				"--max-conn", maxConn,
				"--max-splits", maxSplits,
				"--attempts", attempts,
				"--provider", provider,
			}
			if padAfter != "" {
				args = append(args, "--pad-after", padAfter)
			}
			if provider == "jsoc" {
				args = append(args, "--email", email)
				usedEmail = email
			}
			cmd = exec.Command("python", args...)
		default:
			return DownloadFinishedMsg{Err: fmt.Errorf("unknown protocol")}
		}

		ctx, cancel := context.WithCancel(context.Background())
		cmd = exec.CommandContext(ctx, cmd.Path, cmd.Args[1:]...)
		cmd.Dir = ".." // run from repo root like loader.go so scripts resolve paths correctly.

		stdout, err := cmd.StdoutPipe()
		if err != nil {
			cancel()
			return DownloadFinishedMsg{Err: err}
		}
		stderr, err := cmd.StderrPipe()
		if err != nil {
			cancel()
			return DownloadFinishedMsg{Err: err}
		}

		if err := cmd.Start(); err != nil {
			cancel()
			return DownloadFinishedMsg{Err: err}
		}

		outputCh := make(chan string, 128)
		doneCh := make(chan DownloadFinishedMsg, 1)

		go func() {
			defer close(outputCh)
			defer close(doneCh)

			var b strings.Builder
			var mu sync.Mutex
			var wg sync.WaitGroup

			readPipe := func(r io.ReadCloser) {
				defer wg.Done()
				defer func() {
					_ = r.Close()
				}()
				scanner := bufio.NewScanner(r)
				for scanner.Scan() {
					line := scanner.Text()
					outputCh <- line
					mu.Lock()
					b.WriteString(line)
					b.WriteByte('\n')
					mu.Unlock()
				}
			}

			wg.Add(2)
			go readPipe(stdout)
			go readPipe(stderr)

			err := cmd.Wait()
			wg.Wait()

			doneCh <- DownloadFinishedMsg{
				Output:   strings.TrimSpace(b.String()),
				Email:    usedEmail,
				Err:      err,
				Canceled: ctx.Err() == context.Canceled,
			}
		}()

		return DownloadStartedMsg{
			OutputCh: outputCh,
			DoneCh:   doneCh,
			Cancel:   cancel,
		}
	}
}
