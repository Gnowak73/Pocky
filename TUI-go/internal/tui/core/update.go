package core

import (
	"regexp"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/pocky/tui-go/internal/tui/chrome"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/downloads"
	"github.com/pocky/tui-go/internal/tui/flares"
	"github.com/charmbracelet/lipgloss"
)

var ansiRE = regexp.MustCompile(`\x1b\[[0-9;]*[A-Za-z]`)

// The cycle of the TUI is Init() -> return tea.Cmd function -> eval tea.Cmd
// Then we go into the loop of Update() -> return model + tea.Cmd -> View()
// -> eval tea.Cmd from Update -> Update(). Update takes in the model to mutate it
// along with a tea.Cmd which will be ran to get a new tea.Msg.

// Tea will automatically take messages and pass them etc.
// tea.Cmd is a function type that returns a tea.Msg to tell the TUI to update.
// Since tea.Msg is empty interface, a tickMsg is a tea.Msg.
// We will start with a tick function that will start the initial animations for menus.

// tickMsg is an interface, so we are passing the type and data pointer (16 bytes total).
// This data

func tick() tea.Cmd {
	// We take the time, plug it into the function, return a tick Msg empty struct
	// Note that tea.Msg is an empty interfact type, so any type (such as tickMsg)
	// can be used to satisfy tea.Msg. We set ticks per second, which results in FPS, at 80 ms per tick.
	// This is ONLY used for animations
	return tea.Tick(time.Millisecond*80, func(time.Time) tea.Msg { return tickMsg{} })
}

func (m Model) Init() tea.Cmd {
	// to start, we get a tickMsg then we move to Update()
	return tick()
}

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	// we input a message, then return an updated model along with another
	// message through tea.Cmd

	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		// we need to upate dimensions with terminal size
		m.Width = msg.Width
		m.Height = msg.Height
		if msg.Width > 0 && msg.Height > 0 {
			m.Cache.Viewport.Width = max(msg.Width-6, 20)
			m.Cache.Viewport.Height = max(msg.Height-10, 8)
			m.Download.Viewport.Width = max(msg.Width-24, 60)
			m.Download.Viewport.Height = max((msg.Height-12)/2, 8)
			if m.Mode == ModeDownloadRun {
				m.Download.Output = nil
				m.Download.Viewport.SetContent("")
				m.Download.Viewport.GotoBottom()
			}
			if m.Mode == ModeCacheView && m.Cache.Content != "" {
				// we need to to set new content that matches the smaller
				// window size in view cache
				m.Cache.Viewport.SetContent(m.Cache.Content)
			}
		}
	case tickMsg:
		// frame is the global animation counter. Since we have 60 FPS, we will never overflow
		// with just ints. For 64 bit system we would need 25 billion years of constant runtime.
		m.Frame++
		// for now we are passing m.logo.lines through each frame. Im sure in
		// the future we may find a more efficient method for coloring, maybe cache it
		m.Logo.Colored = chrome.ColorizeLogo(m.Logo.Lines, m.Logo.BlockW, m.Frame)

		// the NoticeFrame is set to the global frame every time we throw an error, and every 20 frames
		// we fizzle our the error notice in the menu.
		if m.Menu.Notice != "" && m.Menu.NoticeFrame > 0 && m.Frame-m.Menu.NoticeFrame > 19 {
			m.Menu.Notice = ""
		}
		if m.Selector.Loading && len(m.Selector.Spinner.Frames) > 0 {
			m.Selector.Spinner.Index = (m.Selector.Spinner.Index + 1) % len(m.Selector.Spinner.Frames)
		}
		// if we started with a tickMsg we end by calling another to
		// keep animations going until we switch message types.
		return m, tick()
	case flares.FlaresLoadedMsg:
		return m.handleFlaresLoaded(msg)
	case downloads.DownloadStartedMsg:
		m.Download.Running = true
		m.Download.OutputCh = msg.OutputCh
		m.Download.DoneCh = msg.DoneCh
		m.Download.Cancel = msg.Cancel
		if m.Width > 0 && m.Height > 0 {
			m.Download.Viewport.Width = max(m.Width-24, 60)
			m.Download.Viewport.Height = max((m.Height-12)/2, 8)
		}
		m.Download.Viewport.SetContent("")
		return m, downloads.ListenDownloadCmd(msg.OutputCh, msg.DoneCh)
	case downloads.DownloadOutputMsg:
		if !m.Download.Running {
			return m, nil
		}
		line := stripANSI(msg.Line)
		if idx := strings.LastIndex(line, "\r"); idx >= 0 {
			line = line[idx+1:]
		}
		innerW := m.Download.Viewport.Width
		if innerW > 0 {
			line = truncateLine(line, innerW)
		}
		if strings.Contains(msg.Line, "\r") && len(m.Download.Output) > 0 {
			m.Download.Output[len(m.Download.Output)-1] = line
		} else {
			m.Download.Output = append(m.Download.Output, line)
		}
		const maxOutputLines = 300
		if len(m.Download.Output) > maxOutputLines {
			m.Download.Output = m.Download.Output[len(m.Download.Output)-maxOutputLines:]
		}
		m.Download.Viewport.SetContent(strings.Join(m.Download.Output, "\n"))
		m.Download.Viewport.GotoBottom()
		return m, downloads.ListenDownloadCmd(m.Download.OutputCh, m.Download.DoneCh)
	case downloads.DownloadFinishedMsg:
		m.Download.Running = false
		m.Download.LastOutput = msg.Output
		m.Download.OutputCh = nil
		m.Download.DoneCh = nil
		m.Download.Cancel = nil
		if msg.Canceled {
			m.Menu.Notice = "Download canceled."
		} else if msg.Err != nil {
			m.Menu.Notice = msg.Err.Error()
		} else {
			m.Menu.Notice = "Download finished."
		}
		m.Menu.NoticeFrame = m.Frame
		if msg.Email != "" {
			m.Cfg.DLEmail = msg.Email
			if err := config.Save(m.Cfg); err != nil {
				m.Menu.Notice = err.Error()
				m.Menu.NoticeFrame = m.Frame
			}
		}
		if m.Mode == ModeDownloadRun {
			if msg.Canceled {
				m.Mode = ModeMain
			} else {
				m.Mode = ModeDownloadForm
			}
		}
		return m, nil
	case tea.KeyMsg:
		return m.handleKeyMsg(msg)
	case tea.MouseMsg:
		return m.handleMouseMsg(msg)
	}
	return m, nil
}

func truncateLine(s string, maxW int) string {
	if maxW <= 0 {
		return s
	}
	if lipgloss.Width(s) <= maxW {
		return s
	}
	var b strings.Builder
	w := 0
	for _, r := range s {
		rw := lipgloss.Width(string(r))
		if w+rw > maxW {
			break
		}
		b.WriteRune(r)
		w += rw
	}
	return b.String()
}

func stripANSI(s string) string {
	return ansiRE.ReplaceAllString(s, "")
}

// next, we go to View() in view.go
