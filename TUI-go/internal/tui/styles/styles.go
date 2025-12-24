// Package styles is built to centralize all the styles that will be used through Lipgloss in
// this programm
package styles

import "github.com/charmbracelet/lipgloss"

var GradientStops = []string{
	"#443066",
	"#FF8855",
	"#FF6B81",
	"#FF4FAD",
	"#D147FF",
	"#8B5EDB",
}

var (
	LogoBox = lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("#8B5EDB")).
		Padding(1, 2)

	StatusBar = lipgloss.NewStyle().
			Background(lipgloss.Color("#353533")).
			Foreground(lipgloss.Color("#E7E7E7"))

	StatusKey = lipgloss.NewStyle().
			Inherit(StatusBar).
			Foreground(StatusBar.GetBackground()).
			Background(lipgloss.Color("#FF7FB3")).
			Padding(0, 1).
			MarginRight(1).
			Bold(true)

		// We inherits the base status bar style so we can
		// customize the text separately in the future.
	StatusText = lipgloss.NewStyle().
			Inherit(StatusBar)

	// later this will be blending with a gradient, so this is just the base
	// color
	StatusHint = lipgloss.NewStyle().
			Inherit(StatusBar).
			Foreground(lipgloss.Color("#D147FF")).
			Padding(0, 1)

	StatusArrow = lipgloss.NewStyle().
			Inherit(StatusBar)

	Version = lipgloss.NewStyle().
		Foreground(lipgloss.Color("#8B5EDB")).
		Bold(true)

	SubcacheStart = "#7D5FFF"

	SubcacheEnd = "#F785D1"

	SubcacheFinal = "#885EDB"

	MenuItem = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#EAEAFF"))

	MenuSelected = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#F785D1"))

	// c stands for color
	Cpurple    = lipgloss.Color("99")
	Cgray      = lipgloss.Color("245")
	ClightGray = lipgloss.Color("241")

	Purple = lipgloss.NewStyle().
		Foreground(lipgloss.Color("99"))

	Gray = lipgloss.NewStyle().
		Foreground(lipgloss.Color("245"))

	LightGray = lipgloss.NewStyle().
			Foreground(lipgloss.Color("241"))

	VeryLightGray = lipgloss.NewStyle().
			Foreground(lipgloss.Color("252"))

	PinkOption = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#FFB7D5"))

	FaintGray = lipgloss.NewStyle().
			Foreground(lipgloss.Color("238"))

	GrayBorder = lipgloss.NewStyle().
			BorderForeground(lipgloss.Color("238"))

	SummaryHeader = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#EAEAFF")).
			Bold(true).
			Padding(0, 1).
			Align(lipgloss.Center)
)
