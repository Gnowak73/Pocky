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
	Canceled bool   // tells the UI the user canceled the dwonload to exit cleanly without error
	Err      error
}

// we do not know how many messages we need to print out to show the terminal. We want a stream. Hence,
// we need a way to take the outputs from python and then pass them off to a viewport immediately
// or with respect to some queue. To do this, we will use channels, which are threat safe and will
// synchronise such that we take a message after listening to the python script and pass it on to
// the go program.

type DownloadStartedMsg struct {
	OutputCh <-chan DownloadOutputMsg   // stream live lines as python runs, python -> viewport
	DoneCh   <-chan DownloadFinishedMsg // send a single final message when process ends
	Cancel   context.CancelFunc         // when called, any command (exec.CommandContext) is killed to abort

	// we require the DoenCh as RunDownloadCmd runs asynchronously, as the UI needs to update
	// while recieving inputs. The goroutine can't return values directly to the update loop,
	// so we send a final result over the doneCh. In the query loader.go, we just return a
	// tea.Cmd what runs the command and returns a FlaresLoadedMsg. We did not use a goroutine
	// there because we only needed one final result (weren't listening or streaming).
}

// we need a way to take the messages from the python output and then format them correctly to the
// viewport. For example, when we have a progress bar load from the download, we will get a message for
// each update in the progress bar. We dont want to print these out on separate lines. Rather, we want to
// take them and replace the old line they were on, to show the animation of the message like seen
// traditionally in the terminal. We will seoncd one of these messages through a channel.

type DownloadOutputMsg struct {
	Line    string // the text from stdout/stderr
	Replace bool   // overwrite the last progress line?
}

func ListenDownloadCmd(outputCh <-chan DownloadOutputMsg, doneCh <-chan DownloadFinishedMsg) tea.Cmd {
	// We wait for the next output or completion message and return it as a tea.Msg, so the UI
	// keeps recieving updates until the download finishes through the Update(). We only use
	// reading channels since we don't need to send any info out.
	return func() tea.Msg {
		if outputCh == nil || doneCh == nil {
			return nil
		}
		select { // waits on multiple channel operations at once and runs first one that's ready
		// we only check the bool "ok" since we use buffered channels, and we dont want zero values recieved
		// from closed channels to appear. "ok" tells us whether a recieved message comes form an open
		// or closed channel. Note deadlock.

		case msg, ok := <-outputCh:
			if ok {
				return msg
			}
			done, ok := <-doneCh
			if ok {
				return done
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
		// same pattern as config.ParentDirFile in loader and config handling. If the user
		// leaves things blank we will return errors. Less hand holding.
		tsv := strings.TrimSpace(state.Form.TSVPath)
		if _, err := os.Stat(tsv); err != nil {
			return DownloadFinishedMsg{
				Err: fmt.Errorf("flare_cache.tsv not found at %s", tsv),
			}
		}

		outDir := strings.TrimSpace(state.Form.OutDir)
		maxConn := strings.TrimSpace(state.Form.MaxConn)
		maxSplits := strings.TrimSpace(state.Form.MaxSplits)
		attempts := strings.TrimSpace(state.Form.Attempts)
		cadence := strings.TrimSpace(state.Form.Cadence)

		// lenient for seconds with or without "s" at the end
		if state.Protocol == ProtocolFido {
			cadence = strings.TrimSuffix(cadence, "s")
		} else if !strings.HasSuffix(cadence, "s") && !strings.HasSuffix(cadence, "S") {
			cadence += "s"
		}
		padBefore := strings.TrimSpace(state.Form.PadBefore)
		padAfter := strings.TrimSpace(state.Form.PadAfter)
		email := strings.TrimSpace(state.Form.Email)
		usedEmail := ""

		// we will make a pointer to a exec.Cmd, a struct which runs external commands. Thus,
		// we can later assign it in a switch statement so it runs the correct python command
		// given the download options.
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

			if provider == "jsoc" && email == "" {
				return DownloadFinishedMsg{Err: fmt.Errorf("JSOC email is required")}
			}

			// Fido uses a different script.
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

		outputCh := make(chan DownloadOutputMsg, 128)
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
				reader := bufio.NewReader(r)
				var lineBuf strings.Builder
				flush := func(replace bool) {
					text := lineBuf.String()
					lineBuf.Reset()
					if text == "" {
						return
					}
					outputCh <- DownloadOutputMsg{Line: text, Replace: replace}
					mu.Lock()
					b.WriteString(text)
					b.WriteByte('\n')
					mu.Unlock()
				}
				for {
					ch, err := reader.ReadByte()
					if err != nil {
						if err == io.EOF {
							flush(false)
							return
						}
						return
					}
					switch ch {
					case '\r':
						text := lineBuf.String()
						lineBuf.Reset()
						if text == "" {
							continue
						}
						outputCh <- DownloadOutputMsg{Line: text, Replace: true}
						mu.Lock()
						b.WriteString(text)
						b.WriteByte('\n')
						mu.Unlock()
					case '\n':
						flush(false)
					default:
						_ = lineBuf.WriteByte(ch)
					}
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
