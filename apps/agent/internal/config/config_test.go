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

func TestDefaultTrafficToolsResolveFromRepositoryResourcesInSourceMode(t *testing.T) {
	root := t.TempDir()
	agentRoot := filepath.Join(root, "apps", "agent")
	fping := filepath.Join(root, "resources", "tools", "windows-x64", "fping", "fping.exe")
	if err := os.MkdirAll(filepath.Dir(fping), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(fping, []byte("tool"), 0o600); err != nil {
		t.Fatal(err)
	}
	cfg := &Config{
		BaseDir: agentRoot,
	}
	cfg.Tools.FpingWindowsX64 = DefaultFpingWindowsX64

	if got := cfg.FpingPath(); got != fping {
		t.Fatalf("source-mode fping path = %q, want %q", got, fping)
	}
}

func TestDefaultTrafficToolsResolveFromAgentExampleConfigDirectory(t *testing.T) {
	root := t.TempDir()
	configDir := filepath.Join(root, "apps", "agent", "resources", "config")
	fping := filepath.Join(root, "resources", "tools", "windows-x64", "fping", "fping.exe")
	if err := os.MkdirAll(filepath.Dir(fping), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(fping, []byte("tool"), 0o600); err != nil {
		t.Fatal(err)
	}
	cfg := &Config{BaseDir: configDir}
	cfg.Tools.FpingWindowsX64 = DefaultFpingWindowsX64

	if got := cfg.FpingPath(); got != fping {
		t.Fatalf("example-config fping path = %q, want %q", got, fping)
	}
}

func TestDefaultTrafficToolsResolveFromDevelopmentRuntimeConfig(t *testing.T) {
	root := t.TempDir()
	configDir := filepath.Join(root, ".local", "agent")
	fping := filepath.Join(root, "resources", "tools", "windows-x64", "fping", "fping.exe")
	if err := os.MkdirAll(filepath.Dir(fping), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(fping, []byte("tool"), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("NETCONSOLE_AGENT_PROJECT_ROOT", root)
	cfg := &Config{BaseDir: configDir}
	cfg.Tools.FpingWindowsX64 = DefaultFpingWindowsX64

	if got := cfg.FpingPath(); got != fping {
		t.Fatalf("development-runtime fping path = %q, want %q", got, fping)
	}
}

func TestResolveConfigPathHonorsExplicitAndEnvironmentOrder(t *testing.T) {
	root := t.TempDir()
	projectConfig := filepath.Join(root, ".local", "agent", "config.json")
	homeConfig := filepath.Join(root, "home", "config.json")
	if err := os.MkdirAll(filepath.Dir(projectConfig), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(homeConfig), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(projectConfig, []byte("{}"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(homeConfig, []byte("{}"), 0o600); err != nil {
		t.Fatal(err)
	}

	t.Setenv("NETCONSOLE_AGENT_CONFIG", "")
	t.Setenv("NETCONSOLE_AGENT_PROJECT_ROOT", root)
	t.Setenv("NETCONSOLE_AGENT_HOME", filepath.Join(root, "home"))
	t.Setenv("LOCALAPPDATA", filepath.Join(root, "localappdata"))
	if got := ResolveConfigPath(""); got != projectConfig {
		t.Fatalf("project-local config = %q, want %q", got, projectConfig)
	}

	envConfig := filepath.Join(root, "override", "config.json")
	t.Setenv("NETCONSOLE_AGENT_CONFIG", envConfig)
	if got := ResolveConfigPath(""); got != envConfig {
		t.Fatalf("environment config = %q, want %q", got, envConfig)
	}

	if got := ResolveConfigPath("explicit.json"); got != "explicit.json" {
		t.Fatalf("explicit config = %q, want explicit.json", got)
	}
}
