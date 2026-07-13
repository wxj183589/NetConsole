package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

const (
	DefaultIperf3WindowsX64      = "./tools/windows-x64/iperf3/iperf3.exe"
	DefaultFpingWindowsX64       = "./tools/windows-x64/fping/fping.exe"
	DefaultMRCollectorWindowsX64 = "./tools/windows-x64/mr_collector/netconsole-mr-collector.exe"
)

var executablePath = os.Executable

type Config struct {
	Agent struct {
		ID         string `json:"id"`
		Name       string `json:"name"`
		ListenHost string `json:"listen_host"`
		ListenPort int    `json:"listen_port"`
		DataDir    string `json:"data_dir"`
		LogDir     string `json:"log_dir"`
		PackageDir string `json:"package_dir"`
	} `json:"agent"`
	Security struct {
		Token       string `json:"token"`
		WebUsername string `json:"web_username"`
		WebPassword string `json:"web_password"`
		EnableAuth  bool   `json:"enable_auth"`
	} `json:"security"`
	Tools struct {
		Iperf3WindowsX64      string `json:"iperf3_windows_x64"`
		FpingWindowsX64       string `json:"fping_windows_x64"`
		MRCollectorWindowsX64 string `json:"mr_collector_windows_x64"`
	} `json:"tools"`
	Runtime struct {
		AutoPackageOnStop bool `json:"auto_package_on_stop"`
		KeepTaskDays      int  `json:"keep_task_days"`
		KeepPackageDays   int  `json:"keep_package_days"`
	} `json:"runtime"`
	PingProbe struct {
		DefaultIntervalMS int `json:"default_interval_ms"`
		DefaultTimeoutMS  int `json:"default_timeout_ms"`
		DefaultPacketSize int `json:"default_packet_size"`
		MaxTargets        int `json:"max_targets"`
		DefaultTCPPort    int `json:"default_tcp_port"`
	} `json:"ping_probe"`
	Power struct {
		PreventSleepOnStart          bool `json:"prevent_sleep_on_start"`
		KeepDisplayOnWhenTaskRunning bool `json:"keep_display_on_when_task_running"`
		RestoreOnExit                bool `json:"restore_on_exit"`
	} `json:"power"`
	BaseDir string `json:"-"`
}

func Load(path string) (*Config, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return nil, err
	}
	b, err := os.ReadFile(abs)
	if err != nil {
		return nil, fmt.Errorf("读取配置失败 %s: %w", abs, err)
	}
	var cfg Config
	if err := json.Unmarshal(b, &cfg); err != nil {
		return nil, fmt.Errorf("解析配置失败: %w", err)
	}
	cfg.BaseDir = filepath.Dir(abs)
	if cfg.Agent.ID == "" || cfg.Agent.Name == "" || cfg.Agent.ListenPort <= 0 {
		return nil, fmt.Errorf("配置缺少 agent.id、agent.name 或有效 listen_port")
	}
	if cfg.PingProbe.MaxTargets <= 0 {
		cfg.PingProbe.MaxTargets = 16
	}
	if cfg.PingProbe.DefaultTCPPort <= 0 {
		cfg.PingProbe.DefaultTCPPort = 80
	}
	if cfg.Tools.Iperf3WindowsX64 == "" {
		cfg.Tools.Iperf3WindowsX64 = DefaultIperf3WindowsX64
	}
	if cfg.Tools.FpingWindowsX64 == "" {
		cfg.Tools.FpingWindowsX64 = DefaultFpingWindowsX64
	}
	if cfg.Tools.MRCollectorWindowsX64 == "" {
		cfg.Tools.MRCollectorWindowsX64 = DefaultMRCollectorWindowsX64
	}
	var raw struct {
		Power map[string]json.RawMessage `json:"power"`
	}
	_ = json.Unmarshal(b, &raw)
	if _, ok := raw.Power["prevent_sleep_on_start"]; !ok {
		cfg.Power.PreventSleepOnStart = true
	}
	if _, ok := raw.Power["keep_display_on_when_task_running"]; !ok {
		cfg.Power.KeepDisplayOnWhenTaskRunning = true
	}
	if _, ok := raw.Power["restore_on_exit"]; !ok {
		cfg.Power.RestoreOnExit = true
	}
	for _, dir := range []string{cfg.DataPath(), cfg.LogPath(), cfg.PackagePath()} {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return nil, fmt.Errorf("创建运行目录失败 %s: %w", dir, err)
		}
	}
	return &cfg, nil
}

func (c *Config) Resolve(path string) string {
	path = os.ExpandEnv(path)
	if strings.HasPrefix(path, "%") && strings.HasSuffix(path, "%") {
		name := strings.Trim(path, "%")
		if value := os.Getenv(name); value != "" {
			path = strings.Replace(path, "%"+name+"%", value, 1)
		}
	}
	if filepath.IsAbs(path) {
		return filepath.Clean(path)
	}
	return filepath.Clean(filepath.Join(c.BaseDir, path))
}

func (c *Config) DataPath() string    { return c.Resolve(c.Agent.DataDir) }
func (c *Config) LogPath() string     { return c.Resolve(c.Agent.LogDir) }
func (c *Config) PackagePath() string { return c.Resolve(c.Agent.PackageDir) }
func (c *Config) IperfPath() string {
	return c.resolveRuntimeTool(c.Tools.Iperf3WindowsX64, DefaultIperf3WindowsX64)
}
func (c *Config) FpingPath() string {
	return c.resolveRuntimeTool(c.Tools.FpingWindowsX64, DefaultFpingWindowsX64)
}
func (c *Config) MRCollectorPath() string {
	return c.resolveRuntimeTool(c.Tools.MRCollectorWindowsX64, DefaultMRCollectorWindowsX64)
}
func (c *Config) ListenAddress() string {
	return fmt.Sprintf("%s:%d", c.Agent.ListenHost, c.Agent.ListenPort)
}

// ResolveConfigPath returns the runtime config path without treating an example
// config as an active configuration. The CLI and environment variables are
// explicit overrides; the remaining candidates are runtime locations.
func ResolveConfigPath(explicit string) string {
	if path := strings.TrimSpace(explicit); path != "" {
		return path
	}
	if path := strings.TrimSpace(os.Getenv("NETCONSOLE_AGENT_CONFIG")); path != "" {
		return path
	}

	candidates := make([]string, 0, 4)
	if root := strings.TrimSpace(os.Getenv("NETCONSOLE_AGENT_PROJECT_ROOT")); root != "" {
		candidates = append(candidates, filepath.Join(root, ".local", "agent", "config.json"))
	}
	if home := strings.TrimSpace(os.Getenv("NETCONSOLE_AGENT_HOME")); home != "" {
		candidates = append(candidates, filepath.Join(home, "config.json"))
	}
	if localAppData := strings.TrimSpace(os.Getenv("LOCALAPPDATA")); localAppData != "" {
		candidates = append(candidates, filepath.Join(localAppData, "NetConsole", "Agent", "config.json"))
	}
	if executable, err := os.Executable(); err == nil {
		candidates = append(candidates, filepath.Join(filepath.Dir(executable), "config.json"))
	}
	for _, candidate := range candidates {
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			return candidate
		}
	}
	if len(candidates) > 0 {
		return candidates[0]
	}
	return "config.json"
}

// ResolveTargetsPath keeps editable targets beside the active config unless
// the caller or environment explicitly selects another file.
func ResolveTargetsPath(explicit, configDir string) string {
	if path := strings.TrimSpace(explicit); path != "" {
		return path
	}
	if path := strings.TrimSpace(os.Getenv("NETCONSOLE_AGENT_TARGETS")); path != "" {
		return path
	}
	if configDir != "" {
		return filepath.Join(configDir, "targets.json")
	}
	return "targets.json"
}

func (c *Config) resolveRuntimeTool(configured, defaultPath string) string {
	configured = strings.TrimSpace(configured)
	if configured != "" && filepath.Clean(configured) != filepath.Clean(defaultPath) {
		return c.Resolve(configured)
	}

	fallback := c.Resolve(defaultPath)
	deliveryRelative := filepath.FromSlash(strings.TrimPrefix(filepath.ToSlash(defaultPath), "./"))
	resourceRelative := filepath.FromSlash(strings.TrimPrefix(filepath.ToSlash(deliveryRelative), "tools/"))
	candidates := make([]string, 0, 6)
	seen := make(map[string]struct{})
	addCandidate := func(path string) {
		cleaned := filepath.Clean(path)
		key := strings.ToLower(filepath.ToSlash(cleaned))
		if _, exists := seen[key]; exists {
			return
		}
		seen[key] = struct{}{}
		candidates = append(candidates, cleaned)
	}

	if executable, err := executablePath(); err == nil && strings.TrimSpace(executable) != "" {
		addCandidate(filepath.Join(filepath.Dir(executable), deliveryRelative))
	}
	if root := strings.TrimSpace(os.Getenv("NETCONSOLE_AGENT_PROJECT_ROOT")); root != "" {
		addCandidate(filepath.Join(root, "resources", "tools", resourceRelative))
	}
	for directory := filepath.Clean(c.BaseDir); ; directory = filepath.Dir(directory) {
		addCandidate(filepath.Join(directory, "resources", "tools", resourceRelative))
		parent := filepath.Dir(directory)
		if parent == directory {
			break
		}
	}
	addCandidate(fallback)

	for _, candidate := range candidates {
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			return candidate
		}
	}
	return fallback
}
