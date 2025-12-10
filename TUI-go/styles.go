package main

import "github.com/charmbracelet/lipgloss"

var gradientStops = []string{
	"#443066",
	"#FF8855",
	"#FF6B81",
	"#FF4FAD",
	"#D147FF",
	"#8B5EDB",
}

var (
	logoBoxStyle = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("#8B5EDB")).
			Padding(1, 2)

	statusBarStyle = lipgloss.NewStyle().
			Background(lipgloss.Color("#353533")).
			Foreground(lipgloss.Color("#E7E7E7"))

	statusKeyStyle = lipgloss.NewStyle().
			Inherit(statusBarStyle).
			Foreground(statusBarStyle.GetBackground()).
			Background(lipgloss.Color("#FF7FB3")).
			Padding(0, 1).
			MarginRight(1).
			Bold(true)

		// We inherits the base status bar style so we can
		// customize the text separately in the future.
	statusTextStyle = lipgloss.NewStyle().
			Inherit(statusBarStyle)

	// later this will be blending with a gradient, so this is just the base
	// color
	statusHintStyle = lipgloss.NewStyle().
			Inherit(statusBarStyle).
			Foreground(lipgloss.Color("#D147FF")).
			Padding(0, 1)

	statusArrowStyle = lipgloss.NewStyle().
				Inherit(statusBarStyle)

	versionStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#8B5EDB")).
			Bold(true)

	menuItemStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#EAEAFF"))

	menuSelectedStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#F785D1"))

	grayStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("245"))

	lightGrayStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("241"))

	veryLightGrayStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("252"))

	pinkOptionStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#FFB7D5"))

	faintGrayStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("238"))

	grayBorderStyle = lipgloss.NewStyle().
			BorderForeground(lipgloss.Color("238"))

	summaryHeaderStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#EAEAFF")).
				Bold(true).
				Padding(0, 1).
				Align(lipgloss.Center)
)
