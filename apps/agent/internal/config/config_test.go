package config

import (
	"os"
	"path/filepath"
	"testing"
)

func useExecutablePath(t *testing.T, path string) {
	t.Helper()
	original := executablePath
	executablePath = func() (string, error) { return path, nil }
	t.Cleanup(func() { executablePath = original })
}

func writeTool(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("tool"), 0o600); err != nil {
		t.Fatal(err)
	}
}

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
	writeTool(t, fping)
	t.Setenv("NETCONSOLE_AGENT_PROJECT_ROOT", "")
	useExecutablePath(t, filepath.Join(root, "bin", "netconsole-agent.exe"))
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
	writeTool(t, fping)
	t.Setenv("NETCONSOLE_AGENT_PROJECT_ROOT", "")
	useExecutablePath(t, filepath.Join(root, "bin", "netconsole-agent.exe"))
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
	writeTool(t, fping)
	t.Setenv("NETCONSOLE_AGENT_PROJECT_ROOT", root)
	useExecutablePath(t, filepath.Join(root, "bin", "netconsole-agent.exe"))
	cfg := &Config{BaseDir: configDir}
	cfg.Tools.FpingWindowsX64 = DefaultFpingWindowsX64

	if got := cfg.FpingPath(); got != fping {
		t.Fatalf("development-runtime fping path = %q, want %q", got, fping)
	}
}

func TestDefaultRuntimeToolsPreferDeliveryDirectory(t *testing.T) {
	root := t.TempDir()
	delivery := filepath.Join(root, "dist", "agent", "windows-x64")
	executable := filepath.Join(delivery, "netconsole-agent-console.exe")
	localConfigDir := filepath.Join(root, "localappdata", "NetConsole", "Agent")
	useExecutablePath(t, executable)
	t.Setenv("NETCONSOLE_AGENT_PROJECT_ROOT", "")

	wantIperf := filepath.Join(delivery, "tools", "windows-x64", "iperf3", "iperf3.exe")
	wantFping := filepath.Join(delivery, "tools", "windows-x64", "fping", "fping.exe")
	wantMR := filepath.Join(delivery, "tools", "windows-x64", "mr_collector", "netconsole-mr-collector.exe")
	for _, path := range []string{wantIperf, wantFping, wantMR} {
		writeTool(t, path)
	}

	cfg := &Config{BaseDir: localConfigDir}
	cfg.Tools.Iperf3WindowsX64 = DefaultIperf3WindowsX64
	cfg.Tools.FpingWindowsX64 = DefaultFpingWindowsX64
	cfg.Tools.MRCollectorWindowsX64 = DefaultMRCollectorWindowsX64
	if got := cfg.IperfPath(); got != wantIperf {
		t.Fatalf("delivery iperf3 path = %q, want %q", got, wantIperf)
	}
	if got := cfg.FpingPath(); got != wantFping {
		t.Fatalf("delivery fping path = %q, want %q", got, wantFping)
	}
	if got := cfg.MRCollectorPath(); got != wantMR {
		t.Fatalf("delivery MR collector path = %q, want %q", got, wantMR)
	}
}

func TestExplicitToolPathsResolveFromActiveConfigDirectory(t *testing.T) {
	root := t.TempDir()
	configDir := filepath.Join(root, "localappdata", "NetConsole", "Agent")
	absolute := filepath.Join(root, "custom", "iperf3.exe")
	cfg := &Config{BaseDir: configDir}
	cfg.Tools.Iperf3WindowsX64 = absolute
	cfg.Tools.FpingWindowsX64 = filepath.Join("custom", "fping.exe")
	cfg.Tools.MRCollectorWindowsX64 = filepath.Join("custom", "netconsole-mr-collector.exe")

	if got := cfg.IperfPath(); got != absolute {
		t.Fatalf("absolute iperf3 path = %q, want %q", got, absolute)
	}
	if got, want := cfg.FpingPath(), filepath.Join(configDir, "custom", "fping.exe"); got != want {
		t.Fatalf("relative fping path = %q, want %q", got, want)
	}
	if got, want := cfg.MRCollectorPath(), filepath.Join(configDir, "custom", "netconsole-mr-collector.exe"); got != want {
		t.Fatalf("relative MR collector path = %q, want %q", got, want)
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
