package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadAppliesStandardToolPaths(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "config.json")
	content := `{"agent":{"id":"a1","name":"Agent","listen_host":"127.0.0.1","listen_port":18080,"data_dir":"data","log_dir":"logs","package_dir":"packages"}}`
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	cfg, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Tools.Iperf3WindowsX64 != DefaultIperf3WindowsX64 || cfg.Tools.FpingWindowsX64 != DefaultFpingWindowsX64 {
		t.Fatalf("unexpected defaults: %#v", cfg.Tools)
	}
}
