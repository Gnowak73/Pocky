// Package downloads holds the structs, information, and logic required to prompt the user and efficiently download
// fits files from the go TUI.
package downloads

import (
	"context"
	"strings"

	"github.com/charmbracelet/bubbles/viewport"
	"github.com/pocky/tui-go/internal/tui/config"
)

type (
	Protocol string // the server protocol for download (e.g., Fido and DRMS)
	Provider string // a string type for the provider
	Level    string // a string stype for the data level FITs
)

const (
	ProviderJSOC Provider = "jsoc"
	ProviderVSO  Provider = "vso"
	Level1       Level    = "lvl1"
	Level1p5     Level    = "lvl1.5"
	ProtocolDRMS Protocol = "drms"
	ProtocolFido Protocol = "fido"
)

type DownloadForm struct {
	Provider  Provider // JSOC or VSO for Fido; ignored for DRMS
	Email     string   // email input
	TSVPath   string   // path to the flare cache
	OutDir    string   // output for the downloads
	MaxConn   string   // connections for downloads
	MaxSplits string   // the per-file split count. How many chunks a single file is split into for parallel downloading.
	Attempts  string   // how many retries for download
	Cadence   string   // cadence of the instrument, usually 12s
	PadBefore string   // how many minutes before the flare start to record
	PadAfter  string   // how many minutes are the flare start to record
}

type DownloadState struct {
	MenuItems    []string // items for the selection menu
	MenuSelected int      // index of selected item
	LastErr      string   // last error thrown
	Protocol     Protocol
	Level        Level          // which level of fits data is chosen
	Form         DownloadForm   // argument information required for python scripts
	Focus        int            // the index of the currently active form field
	Running      bool           // download in progress?
	LastOutput   string         // capture stdout/stderr for display
	Output       []string       // running output buffer for the viewport
	Viewport     viewport.Model // shows terminal output for python scripts
	OutputCh     <-chan DownloadOutputMsg
	DoneCh       <-chan DownloadFinishedMsg
	Cancel       context.CancelFunc
	Confirming  bool // confirm before running the download
}

func NewDownloadState(cfg config.Config) DownloadState {
	tsvPath := config.ParentDirFile("flare_cache.tsv")
	if tsvPath == "" {
		tsvPath = "flare_cache.tsv"
	}
	outDir := config.ParentDirFile("data_aia_lvl1")
	if outDir == "" {
		outDir = "data_aia_lvl1"
	}
	email := strings.TrimSpace(cfg.DLEmail)

	menu := []string{
		"JSOC DRMS Lvl 1",
		"JSOC DRMS Lvl 1.5",
		"Fido Fetch Lvl 1",
		"Back",
	}

	downloadForm := DownloadForm{
		Email:     email,
		TSVPath:   tsvPath,
		OutDir:    outDir,
		MaxConn:   "6",
		MaxSplits: "3",
		Attempts:  "5",
		Cadence:   "12s",
		PadBefore: "0",
		PadAfter:  "",
	}

	return DownloadState{
		MenuItems:    menu,
		MenuSelected: 0,
		Level:        Level1,
		Form:         downloadForm,
		Viewport:     viewport.New(80, 20),
	}
}
