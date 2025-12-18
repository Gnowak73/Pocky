package core

type tickMsg struct{}

type ViewMode int

const (
	ModeMain ViewMode = iota
	ModeWavelength
	ModeDateRange
	ModeFlare
	ModeSelectFlares
	ModeCacheView
	ModeCacheDelete
)
