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

func testAgentDataRoot(t *testing.T) string {
	t.Helper()
	base := `D:\study\NetConsole-Workspace\test-data\NetConsole`
	if err := os.MkdirAll(base, 0o755); err != nil {
		t.Fatal(err)
	}
	root, err := os.MkdirTemp(base, "agent-go-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(root) })
	return root
}

func TestLoadAppliesStandardToolPaths(t *testing.T) {
	dataRoot := testAgentDataRoot(t)
	path := filepath.Join(dataRoot, "agents", "test-agent", "config.json")
	t.Setenv("NETCONSOLE_DATA_ROOT", dataRoot)
	content := `{"agent":{"id":"a1","name":"Agent","listen_host":"127.0.0.1","listen_port":18080,"data_dir":"data","log_dir":"logs","package_dir":"packages"}}`
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
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

func TestResolveConfigPathUsesUnifiedAgentStorage(t *testing.T) {
	root := t.TempDir()
	dataRoot := testAgentDataRoot(t)
	homeConfig := filepath.Join(dataRoot, "agents", "local", "config.json")
	if err := os.MkdirAll(filepath.Dir(homeConfig), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(homeConfig, []byte("{}"), 0o600); err != nil {
		t.Fatal(err)
	}

	t.Setenv("NETCONSOLE_DATA_ROOT", dataRoot)
	t.Setenv("NETCONSOLE_AGENT_CONFIG", "")
	t.Setenv("NETCONSOLE_AGENT_HOME", "")
	if got, err := ResolveConfigPath(""); err != nil || got != homeConfig {
		t.Fatalf("default config = %q, %v; want %q", got, err, homeConfig)
	}

	envConfig := filepath.Join(dataRoot, "agents", "secondary", "config.json")
	t.Setenv("NETCONSOLE_AGENT_CONFIG", envConfig)
	if got, err := ResolveConfigPath(""); err != nil || got != envConfig {
		t.Fatalf("environment config = %q, %v; want %q", got, err, envConfig)
	}

	if _, err := ResolveConfigPath(filepath.Join(root, "outside", "config.json")); err == nil {
		t.Fatal("expected an external config path to be rejected")
	}
	if _, err := ResolveConfigPath("config.json"); err == nil {
		t.Fatal("expected a relative config path to be rejected")
	}
}

func TestLoadRejectsRuntimePathOutsideUnifiedAgentStorage(t *testing.T) {
	root := t.TempDir()
	dataRoot := testAgentDataRoot(t)
	configPath := filepath.Join(dataRoot, "agents", "local", "config.json")
	t.Setenv("NETCONSOLE_DATA_ROOT", dataRoot)
	content := `{"agent":{"id":"a1","name":"Agent","listen_host":"127.0.0.1","listen_port":18080,"data_dir":"` + filepath.ToSlash(filepath.Join(root, "outside")) + `","log_dir":"logs","package_dir":"packages"}}`
	if err := os.MkdirAll(filepath.Dir(configPath), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(configPath, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(configPath); err == nil {
		t.Fatal("expected an external Agent runtime directory to be rejected")
	}
}
