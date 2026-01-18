//go:build !windows

package downloads

import (
	"io"
	"os"
	"os/exec"
	"strings"
	"syscall"

	"github.com/creack/pty"
)

func startDownloadProcess(cmd *exec.Cmd, cols, rows int) (io.ReadCloser, func(int, int), error) {
	// start the command inside a PTY so tqdm detects a real terminal
	// and renders multi-line progress with cursor movement.
	if cols <= 0 {
		cols = 80
	}
	if rows <= 0 {
		rows = 24
	}
	env := make([]string, 0, len(os.Environ()))
	for _, v := range os.Environ() {
		if strings.HasPrefix(v, "COLUMNS=") || strings.HasPrefix(v, "LINES=") {
			continue
		}
		env = append(env, v)
	}
	cmd.Env = append(
		env,
		"TERM=xterm-256color",
		"PYTHONUNBUFFERED=1",
	)
	f, err := pty.StartWithSize(cmd, &pty.Winsize{
		Cols: uint16(cols),
		Rows: uint16(rows),
	})
	if err != nil {
		return nil, nil, err
	}
	resize := func(cols, rows int) {
		if cols <= 0 || rows <= 0 {
			return
		}
		_ = pty.Setsize(f, &pty.Winsize{
			Cols: uint16(cols),
			Rows: uint16(rows),
		})
		if cmd.Process != nil {
			_ = cmd.Process.Signal(syscall.SIGWINCH)
		}
	}
	return f, resize, nil
}
