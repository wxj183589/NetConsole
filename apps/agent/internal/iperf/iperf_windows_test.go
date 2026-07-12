//go:build windows

package iperf

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"netconsole-agent/internal/core"
)

func TestCommandRunnerCapturesWindowsStdout(t *testing.T) {
	dir := t.TempDir()
	raw := filepath.Join(dir, "raw")
	if err := os.Mkdir(raw, 0o755); err != nil {
		t.Fatal(err)
	}
	tool := os.Getenv("COMSPEC")
	if tool == "" {
		t.Fatal("COMSPEC is empty")
	}
	runner := commandRunner(tool, []string{"/d", "/c", "echo iperf-output&&cd"}, 0, "client")
	if err := runner(&core.Runtime{TaskID: "test", Dir: dir, RawDir: raw, Ctx: context.Background()}); err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(filepath.Join(raw, "iperf_raw.log"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(b), "iperf-output") {
		t.Fatalf("raw output=%q", string(b))
	}
	if !strings.Contains(strings.ToLower(string(b)), strings.ToLower(filepath.Dir(tool))) {
		t.Fatalf("process work directory is not executable directory: %q", string(b))
	}
}
