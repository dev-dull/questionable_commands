package main

import (
	"fmt"
	"os"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

const tickInterval = 150 * time.Millisecond

var (
	borderStyle = lipgloss.NewStyle().
			BorderStyle(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("#BD93F9")).
			Padding(1, 4)
)

var spinners = []string{"⠋", "⠙", "⠹", "⠸", "⠴", "⠦", "⠧", "⠇", "⠏"}

type model struct {
	cursor  int
	width   int
	height  int
	paused  bool
}

func initialModel() model { return model{} }

func (m model) Init() tea.Cmd { return tickCmd() }

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		return m, nil
	case tea.KeyMsg:
		switch msg.String() {
		case "q", "ctrl+c":
			return m, tea.Quit
		case " ":
			m.paused = !m.paused
			if m.paused {
				return m, nil
			}
			return m, tickCmd()
		}
		return m, nil
	case tickMsg:
		m.cursor = (m.cursor + 1) % len(spinners)
		if m.paused {
			return m, nil
		}
		return m, tickCmd()
	}
	return m, nil
}

func (m model) View() string {
	box := m.renderBox()

	centerX := (m.width - lipgloss.Width(box)) / 2
	centerY := (m.height - lipgloss.Height(box)) / 2

	topPad := strings.Repeat("\n", max(0, centerY))
	leftPad := strings.Repeat(" ", max(0, centerX))

	lines := strings.Split(box, "\n")
	for i, line := range lines {
		lines[i] = leftPad + line
	}
	return topPad + strings.Join(lines, "\n")
}

func (m model) renderBox() string {
	// No styling on content lines — just plain text.
	// If the border aligns with this, the issue is ANSI codes / nested rendering.
	content := lipgloss.JoinVertical(lipgloss.Center,
		fmt.Sprintf("Hello, World! %s", spinners[m.cursor]),
		"press space to pause, q to quit",
	)
	return borderStyle.Render(content)
}

type tickMsg struct{}

func tickCmd() tea.Cmd {
	return tea.Tick(tickInterval, func(t time.Time) tea.Msg {
		return tickMsg{}
	})
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func main() {
	p := tea.NewProgram(initialModel())
	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
	}
}
