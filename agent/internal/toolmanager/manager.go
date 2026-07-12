package toolmanager

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"netconsole-agent/internal/config"
)

var iperfRequiredFiles = []string{"cygwin1.dll", "cygcrypto-3.dll", "cygz.dll"}

const iperfHint = "请将 iperf3.exe 及 cygwin1.dll、cygcrypto-3.dll、cygz.dll 放到 agent/tools/windows-x64/iperf3/ 目录"

type FileStatus struct {
	Name   string `json:"name"`
	Exists bool   `json:"exists"`
}

type ToolStatus struct {
	Exists        bool         `json:"exists"`
	Ready         bool         `json:"ready"`
	Path          string       `json:"path"`
	WorkDir       string       `json:"work_dir"`
	Version       string       `json:"version,omitempty"`
	Warning       string       `json:"warning,omitempty"`
	RequiredFiles []FileStatus `json:"required_files,omitempty"`
}

type Status struct {
	Iperf3 ToolStatus `json:"iperf3"`
	Fping  ToolStatus `json:"fping"`
}

type UnavailableError struct {
	Message       string       `json:"message"`
	Path          string       `json:"path"`
	Hint          string       `json:"hint"`
	RequiredFiles []FileStatus `json:"required_files,omitempty"`
}

func (e *UnavailableError) Error() string { return e.Message }

type Manager struct{ cfg *config.Config }

func New(cfg *config.Config) *Manager { return &Manager{cfg: cfg} }

func (m *Manager) Status(ctx context.Context) Status {
	return Status{
		Iperf3: m.iperfStatus(ctx),
		Fping:  simpleStatus(m.cfg.FpingPath()),
	}
}

func (m *Manager) RequireIperf3(ctx context.Context) (string, error) {
	status := m.iperfStatus(ctx)
	if !status.Exists {
		return "", &UnavailableError{Message: "未找到 iperf3.exe", Path: status.Path, Hint: iperfHint, RequiredFiles: status.RequiredFiles}
	}
	if !status.Ready {
		return "", &UnavailableError{Message: "iperf3 依赖文件缺失", Path: status.Path, Hint: iperfHint, RequiredFiles: status.RequiredFiles}
	}
	return status.Path, nil
}

func (m *Manager) iperfStatus(parent context.Context) ToolStatus {
	path := m.cfg.IperfPath()
	workDir := filepath.Dir(path)
	status := ToolStatus{Path: path, WorkDir: workDir, Exists: fileExists(path)}
	missing := make([]string, 0)
	for _, name := range iperfRequiredFiles {
		exists := fileExists(filepath.Join(workDir, name))
		status.RequiredFiles = append(status.RequiredFiles, FileStatus{Name: name, Exists: exists})
		if !exists {
			missing = append(missing, name)
		}
	}
	status.Ready = status.Exists && len(missing) == 0
	if !status.Exists {
		status.Warning = "未找到 iperf3.exe"
		return status
	}
	if len(missing) > 0 {
		status.Warning = "依赖文件缺失: " + strings.Join(missing, ", ")
	}
	ctx, cancel := context.WithTimeout(parent, 5*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, path, "--version")
	cmd.Dir = workDir
	prepareCommand(cmd)
	output, err := cmd.CombinedOutput()
	status.Version = firstLine(string(output))
	if err != nil {
		message := fmt.Sprintf("版本检测失败: %v", err)
		if status.Warning == "" {
			status.Warning = message
		} else {
			status.Warning += "; " + message
		}
	}
	return status
}

func simpleStatus(path string) ToolStatus {
	exists := fileExists(path)
	status := ToolStatus{Exists: exists, Ready: exists, Path: path, WorkDir: filepath.Dir(path)}
	if !exists {
		status.Warning = "未找到工具文件"
	}
	return status
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

func firstLine(value string) string {
	for _, line := range strings.Split(strings.ReplaceAll(value, "\r\n", "\n"), "\n") {
		if line = strings.TrimSpace(line); line != "" {
			return line
		}
	}
	return ""
}
