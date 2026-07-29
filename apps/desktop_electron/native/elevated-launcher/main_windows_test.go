//go:build windows

package main

import "testing"

func TestQuoteWindowsArgument(t *testing.T) {
	tests := map[string]string{
		"":                   `""`,
		"plain":              `"plain"`,
		`C:\Program Files\A`: `"C:\Program Files\A"`,
		`value"quoted`:       `"value\"quoted"`,
		`trailing\`:          `"trailing\\"`,
	}
	for input, expected := range tests {
		if actual := quoteWindowsArgument(input); actual != expected {
			t.Fatalf("quoteWindowsArgument(%q) = %q, want %q", input, actual, expected)
		}
	}
}

func TestHasShellToken(t *testing.T) {
	if !hasShellToken("x && calc") || !hasShellToken("x | calc") {
		t.Fatal("hasShellToken did not reject command syntax")
	}
	if hasShellToken("--profile onsite") {
		t.Fatal("hasShellToken rejected a normal argument")
	}
}
