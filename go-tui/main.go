package main

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"syscall"

	"github.com/creack/pty"
	"golang.org/x/term"
)

func main() {
	root := findRepoRoot()
	script := filepath.Join(root, "pocky.sh")

	cmd := exec.Command("bash", script)
	cmd.Dir = root
	cmd.SysProcAttr = &syscall.SysProcAttr{Setctty: true, Setsid: true}

	// start with current terminal size
	cols, rows := 80, 24
	if c, r, err := term.GetSize(int(os.Stdout.Fd())); err == nil {
		cols, rows = c, r
	}

	ptm, err := pty.StartWithSize(cmd, &pty.Winsize{Cols: uint16(cols), Rows: uint16(rows)})
	if err != nil {
		fmt.Println("failed to start pocky.sh:", err)
		os.Exit(1)
	}
	defer ptm.Close()

	// resize on SIGWINCH
	winch := make(chan os.Signal, 1)
	signal.Notify(winch, syscall.SIGWINCH)
	go func() {
		for range winch {
			if c, r, err := term.GetSize(int(os.Stdout.Fd())); err == nil {
				_ = pty.Setsize(ptm, &pty.Winsize{Cols: uint16(c), Rows: uint16(r)})
			}
		}
	}()

	// raw mode for stdin
	oldState, err := term.MakeRaw(int(os.Stdin.Fd()))
	if err != nil {
		fmt.Println("failed to set raw mode:", err)
		return
	}
	defer term.Restore(int(os.Stdin.Fd()), oldState)

	// pump data
	go func() { _, _ = io.Copy(ptm, os.Stdin) }()
	go func() { _, _ = io.Copy(os.Stdout, ptm) }()

	// wait for process
	if err := cmd.Wait(); err != nil {
		fmt.Println("process exited:", err)
	}
}

func findRepoRoot() string {
	dir, _ := os.Getwd()
	for i := 0; i < 5; i++ {
		if _, err := os.Stat(filepath.Join(dir, "pocky.sh")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return dir
}
