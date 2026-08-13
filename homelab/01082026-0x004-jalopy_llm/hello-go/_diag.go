//go:build ignore

package main

import (
	"fmt"
	"os"

	"github.com/charmbracelet/lipgloss"
	"github.com/mattn/go-runewidth"
)

func main() {
	styledBold := lipgloss.NewStyle().
		Foreground(lipgloss.Color("#8BE9FD")).
		Bold(true).
		Italic(true).
		Render("Hello, World!")

	styledPlain := lipgloss.NewStyle().
		Foreground(lipgloss.Color("#8BE9FD")).
		Italic(true).
		Render("Hello, World!")

	fmt.Fprintf(os.Stderr, "=== Bold + Italic ===\n")
	fmt.Fprintf(os.Stderr, "lipgloss.Width:  %d  runewidth: %d  runes: %d\n",
		lipgloss.Width(styledBold), runewidth.StringWidth(styledBold), len([]rune(styledBold)))

	fmt.Fprintf(os.Stderr, "\n=== Italic only ===\n")
	fmt.Fprintf(os.Stderr, "lipgloss.Width:  %d  runewidth: %d  runes: %d\n",
		lipgloss.Width(styledPlain), runewidth.StringWidth(styledPlain), len([]rune(styledPlain)))
}
