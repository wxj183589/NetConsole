package toolmanager

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"netconsole-agent/internal/config"
)

func TestRequireIperfUsesOnlyConfiguredPathAndChecksDLLs(t *testing.T) {
	root := t.TempDir()
	cfg := &config.Config{BaseDir: root}
	cfg.Tools.Iperf3WindowsX64 = config.DefaultIperf3WindowsX64
	cfg.Tools.FpingWindowsX64 = config.DefaultFpingWindowsX64
	manager := New(cfg)

	legacy := filepath.Join(root, "tools", "iperf", "iperf3.exe")
	if err := os.MkdirAll(filepath.Dir(legacy), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(legacy, []byte("legacy"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := manager.RequireIperf3(context.Background()); err == nil {
		t.Fatal("configured path must not fall back to legacy path")
	}

	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	destination := cfg.IperfPath()
	if err := os.MkdirAll(filepath.Dir(destination), 0o755); err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(exe)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(destination, b, 0o700); err != nil {
		t.Fatal(err)
	}
	for _, name := range iperfRequiredFiles {
		if err := os.WriteFile(filepath.Join(filepath.Dir(destination), name), []byte("dll"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	if path, err := manager.RequireIperf3(context.Background()); err != nil || path != destination {
		t.Fatalf("path=%q err=%v", path, err)
	}

	if err := os.Remove(filepath.Join(filepath.Dir(destination), "cygz.dll")); err != nil {
		t.Fatal(err)
	}
	_, err = manager.RequireIperf3(context.Background())
	var unavailable *UnavailableError
	if !errors.As(err, &unavailable) || unavailable.Message != "iperf3 依赖文件缺失" {
		t.Fatalf("error=%v", err)
	}
}

func TestStatusReportsOptionalTools(t *testing.T) {
	original := runProbe
	defer func() { runProbe = original }()
	runProbe = func(_ context.Context, _, _ string, args ...string) (string, error) {
		if len(args) > 0 && args[0] == "-v" {
			return "fping: Version 5.5", nil
		}
		return "-J, --json output in JSON format\n-S, --src=IP set source address", nil
	}
	root := t.TempDir()
	cfg := &config.Config{BaseDir: root}
	cfg.Tools.Iperf3WindowsX64 = config.DefaultIperf3WindowsX64
	cfg.Tools.FpingWindowsX64 = config.DefaultFpingWindowsX64
	path := cfg.FpingPath()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("tool"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(filepath.Dir(path), "cygwin1.dll"), []byte("dll"), 0o600); err != nil {
		t.Fatal(err)
	}
	status := New(cfg).Status(context.Background())
	if !status.Fping.Exists || !status.Fping.Ready || status.Iperf3.Exists {
		t.Fatalf("status=%#v", status)
	}
}
