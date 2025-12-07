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

	statusTextStyle = lipgloss.NewStyle().
			Inherit(statusBarStyle)

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

	menuHelpStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("241"))

	summaryLabelStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#FFB7D5")).
				Width(12).
				Align(lipgloss.Right)

	summaryValueStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#FFB7D5"))

	summaryHeaderStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#EAEAFF")).
				Bold(true).
				Padding(0, 1).
				Align(lipgloss.Center)

	summaryBodyStyle = lipgloss.NewStyle().
				Padding(0, 1).
				Align(lipgloss.Left)

	summaryBorderStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#3A3A3A"))
)
