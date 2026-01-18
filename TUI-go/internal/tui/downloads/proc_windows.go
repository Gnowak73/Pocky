//go:build windows

package downloads

import (
	"io"
	"os"
	"os/exec"
)

func startDownloadProcess(cmd *exec.Cmd, cols, rows int) (io.ReadCloser, func(int, int), error) {
	// Windows fallback: merge stderr into stdout and read a single stream.
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, nil, err
	}
	cmd.Stderr = cmd.Stdout
	cmd.Env = append(os.Environ(), "PYTHONUNBUFFERED=1")
	if err := cmd.Start(); err != nil {
		return nil, nil, err
	}
	return stdout, nil, nil
}
