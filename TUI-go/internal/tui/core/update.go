package core

import (
	"regexp"
	"strconv"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/pocky/tui-go/internal/tui/chrome"
	"github.com/pocky/tui-go/internal/tui/config"
	"github.com/pocky/tui-go/internal/tui/downloads"
	"github.com/pocky/tui-go/internal/tui/flares"
	"github.com/pocky/tui-go/internal/tui/termemu"
)

var ansiRE = regexp.MustCompile(`\x1b\[[0-9;]*[A-Za-z]`)
var percentRE = regexp.MustCompile(`(\d+)%`)

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
			downloadWidth := (msg.Width * 3) / 5
			if msg.Width < 160 {
				downloadWidth = (msg.Width * 4) / 5
			}
			if downloadWidth < 60 {
				downloadWidth = 60
			}
			if downloadWidth > msg.Width-4 {
				downloadWidth = msg.Width - 4
			}
			m.Download.Viewport.Width = downloadWidth
			m.Download.Viewport.Height = max((msg.Height-12)/2, 8)
			if m.Mode == ModeDownloadRun {
				if m.Download.TerminalMode == downloads.TerminalEmulator {
					if m.Download.Emu != nil {
						m.Download.Emu.Resize(m.Download.Viewport.Width)
						m.Download.Viewport.SetContent(m.Download.Emu.Render())
					} else {
						m.Download.Viewport.SetContent("")
					}
					if m.Download.PTYResize != nil {
						m.Download.PTYResize(m.Download.Viewport.Width, m.Download.Viewport.Height)
					}
				} else {
					m.Download.Viewport.SetContent(strings.Join(m.Download.Output, "\n"))
				}
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
		m.Download.PTYResize = msg.Resize
		if m.Width > 0 && m.Height > 0 {
			downloadWidth := (m.Width * 3) / 5
			if m.Width < 160 {
				downloadWidth = (m.Width * 4) / 5
			}
			if downloadWidth < 60 {
				downloadWidth = 60
			}
			if downloadWidth > m.Width-4 {
				downloadWidth = m.Width - 4
			}
			m.Download.Viewport.Width = downloadWidth
			m.Download.Viewport.Height = max((m.Height-12)/2, 8)
			if m.Mode == ModeDownloadRun && m.Download.PTYResize != nil {
				m.Download.PTYResize(m.Download.Viewport.Width, m.Download.Viewport.Height)
			}
		}
		m.Download.Cursor = 0
		m.Download.ProgressIdx = make(map[string]int)
		m.Download.ProgressTime = make(map[string]time.Time)
		m.Download.EventStatus = ""
		m.Download.EventIdx = -1
		m.Download.Follow = true
		m.Download.Output = nil
		if m.Download.TerminalMode == downloads.TerminalEmulator {
			if m.Download.Emu == nil {
				m.Download.Emu = termemu.New(m.Download.Viewport.Width)
			} else {
				m.Download.Emu.Resize(m.Download.Viewport.Width)
			}
			m.Download.Emu.Reset()
			m.Download.Viewport.SetContent("")
		} else {
			m.Download.Viewport.SetContent("")
		}
		return m, downloads.ListenDownloadCmd(msg.OutputCh, msg.DoneCh)
	case downloads.DownloadOutputMsg:
		if !m.Download.Running {
			return m, nil
		}
		if m.Download.TerminalMode == downloads.TerminalEmulator {
			if m.Download.Emu == nil {
				m.Download.Emu = termemu.New(m.Download.Viewport.Width)
			}
			m.Download.Emu.AppendSegment(msg.Line, msg.Replace)
			m.Download.Viewport.SetContent(m.Download.Emu.Render())
		} else {
			applyDownloadOutput(&m.Download, msg, m.Download.Viewport.Width)
			m.Download.Viewport.SetContent(strings.Join(m.Download.Output, "\n"))
		}
		if m.Download.Follow {
			m.Download.Viewport.GotoBottom()
		}
		return m, downloads.ListenDownloadCmd(m.Download.OutputCh, m.Download.DoneCh)
	case downloads.DownloadFinishedMsg:
		m.Download.Running = false
		m.Download.LastOutput = msg.Output
		m.Download.OutputCh = nil
		m.Download.DoneCh = nil
		m.Download.Cancel = nil
		m.Download.PTYResize = nil
		m.Download.ProgressIdx = nil
		m.Download.ProgressTime = nil
		m.Download.EventStatus = ""
		m.Download.EventIdx = -1
		m.Download.DonePrompt = true
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

func applyDownloadOutput(state *downloads.DownloadState, msg downloads.DownloadOutputMsg, width int) {
	raw := msg.Line
	segments := strings.Split(raw, "\r")
	for i, seg := range segments {
		replace := msg.Replace || i > 0 || strings.Contains(raw, "\x1b[2K")
		progressKey := ""
		if idx := strings.Index(seg, ".fits:"); idx > 0 {
			progressKey = strings.TrimSpace(seg[:idx])
		}
		if strings.Contains(seg, "Files Downloaded:") || strings.Contains(seg, "file/s") || strings.Contains(seg, "%|") {
			replace = true
		}
		text := strings.ReplaceAll(seg, "\x1b[2K", "")
		text = stripANSI(text)
		rawText := strings.TrimSpace(text)
		if rawText == "" {
			continue
		}
		if isEventStatusLine(rawText) {
			state.EventStatus = trimEventStatus(rawText)
			if width > 0 {
				rawText = truncateLine(rawText, width)
			}
			if state.EventIdx >= 0 && state.EventIdx < len(state.Output) {
				state.Output[state.EventIdx] = rawText
			} else {
				state.Output = append(state.Output, rawText)
				state.EventIdx = len(state.Output) - 1
			}
			continue
		}
		if width > 0 {
			text = truncateLine(text, width)
		}
		if text == "" {
			continue
		}

		if progressKey != "" {
			if state.ProgressIdx == nil {
				state.ProgressIdx = make(map[string]int)
			}
			if state.ProgressTime == nil {
				state.ProgressTime = make(map[string]time.Time)
			}
			if idx, ok := state.ProgressIdx[progressKey]; ok && idx >= 0 && idx < len(state.Output) {
				state.Output[idx] = text
			} else {
				state.Output = append(state.Output, text)
				state.ProgressIdx[progressKey] = len(state.Output) - 1
			}
			state.ProgressTime[progressKey] = time.Now()
		} else if replace && len(state.Output) > 0 {
			state.Output[len(state.Output)-1] = text
		} else {
			state.Output = append(state.Output, text)
		}
	}

	const maxOutputLines = 300
	if len(state.Output) > maxOutputLines {
		state.Output = state.Output[len(state.Output)-maxOutputLines:]
	}

	pruneProgressLines(state)
}

func pruneProgressLines(state *downloads.DownloadState) {
	if len(state.ProgressIdx) == 0 || len(state.ProgressTime) == 0 {
		return
	}
	now := time.Now()
	for key, idx := range state.ProgressIdx {
		if idx < 0 || idx >= len(state.Output) {
			delete(state.ProgressIdx, key)
			delete(state.ProgressTime, key)
			continue
		}
		line := state.Output[idx]
		percent := parsePercent(line)
		if percent >= 100 {
			removeProgressLine(state, key, idx)
			continue
		}
		if last, ok := state.ProgressTime[key]; ok {
			if percent >= 95 && now.Sub(last) > 2*time.Second {
				removeProgressLine(state, key, idx)
				continue
			}
			if now.Sub(last) > 10*time.Second {
				removeProgressLine(state, key, idx)
			}
		}
	}
}

func isEventStatusLine(line string) bool {
	return strings.Contains(line, " events |") && strings.Contains(line, "/") && strings.HasPrefix(line, "[")
}

func trimEventStatus(line string) string {
	idx := strings.Index(line, "skipped:")
	if idx == -1 {
		return line
	}
	rest := line[idx:]
	next := strings.Index(rest, " | ")
	if next == -1 {
		return line
	}
	return strings.TrimSpace(line[:idx+next])
}


func removeProgressLine(state *downloads.DownloadState, key string, idx int) {
	delete(state.ProgressIdx, key)
	delete(state.ProgressTime, key)
	if idx < 0 || idx >= len(state.Output) {
		return
	}
	state.Output = append(state.Output[:idx], state.Output[idx+1:]...)
	for k, v := range state.ProgressIdx {
		if v > idx {
			state.ProgressIdx[k] = v - 1
		}
	}
}

func parsePercent(line string) int {
	m := percentRE.FindStringSubmatch(line)
	if len(m) < 2 {
		return -1
	}
	val, err := strconv.Atoi(m[1])
	if err != nil {
		return -1
	}
	return val
}

// next, we go to View() in view.go
