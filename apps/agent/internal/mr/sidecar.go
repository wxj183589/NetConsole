package mr

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"netconsole-agent/internal/core"
	"netconsole-agent/internal/util"
)

type sidecarRequest struct {
	Request
	SessionID string            `json:"session_id"`
	Tools     map[string]string `json:"tools"`
}

var requiredRawFiles = []string{
	"init_raw.log", "config_collect_raw.log", "terminal_monitor_raw.log", "mesh_link_raw.log",
	"channel_busy_raw.log", "ap_radio_statistics_raw.log", "switch_history_latest.log", "interface_rate_raw.log",
	"wireless_status_raw.log", "collector_output_raw.log", "fping_v5_raw.log", "fping_v5_samples.jsonl",
	"fping_v5_final_summary.json", "iperf_client_raw.log",
}

// SidecarRunner keeps all MR SSH/Netmiko work in the Python process.
func SidecarRunner(collectorPath, baseDir string, request Request, fpingConfig FpingFollowConfig, fpingPath, iperfPath string) (core.Runner, error) {
	if collectorPath == "" {
		return nil, errors.New("MR 采集器路径为空")
	}
	if info, err := os.Stat(collectorPath); err != nil || info.IsDir() {
		return nil, fmt.Errorf("未找到 MR 采集器: %s", collectorPath)
	}
	return func(rt *core.Runtime) error {
		if err := prepareSidecarSession(rt.Dir); err != nil {
			return err
		}
		safe := SanitizedRequest(request)
		safe.Fping = fpingConfig
		sideReq := sidecarRequest{Request: safe, SessionID: rt.TaskID, Tools: map[string]string{
			"fping_path": fpingPath, "iperf3_path": iperfPath, "ap_map_path": filepath.Join(baseDir, "config", "ap_map.json"),
		}}
		sideReq.Target.Password = request.Target.Password
		requestPath := filepath.Join(rt.Dir, "meta", "request.private.json")
		stopPath := filepath.Join(rt.Dir, "stop.request")
		eventPath := filepath.Join(rt.Dir, "events.jsonl")
		statusPath := filepath.Join(rt.Dir, "status.json")
		if err := util.WriteJSONAtomic(requestPath, sideReq, 0o600); err != nil {
			return err
		}
		logFile, err := os.OpenFile(filepath.Join(rt.Dir, "runtime.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
		if err != nil {
			return err
		}
		defer logFile.Close()
		cmd := exec.Command(collectorPath, "--request", requestPath, "--session-dir", rt.Dir, "--stop-file", stopPath, "--event-file", eventPath, "--status-file", statusPath)
		cmd.Dir = baseDir
		cmd.Env = sidecarUTF8Env(os.Environ())
		cmd.Stdout, cmd.Stderr = logFile, logFile
		if runtime.GOOS == "windows" {
			prepareSidecarCommand(cmd)
		}
		rt.Log("启动 MR Netmiko sidecar path=%s", collectorPath)
		if err := cmd.Start(); err != nil {
			return fmt.Errorf("启动 MR 采集器失败: %w", err)
		}
		done := make(chan error, 1)
		go func() { done <- cmd.Wait() }()
		select {
		case <-rt.Ctx.Done():
			_ = os.WriteFile(stopPath, []byte(time.Now().Format(time.RFC3339Nano)+" user_stop\n"), 0o600)
			select {
			case <-done:
				return context.Canceled
			case <-time.After(20 * time.Second):
				_ = stopSidecarProcess(cmd.Process)
				<-done
				return context.Canceled
			}
		case err := <-done:
			if err != nil && !hasCollectorOutput(rt.Dir) {
				return fmt.Errorf("MR 采集器异常退出: %w", err)
			}
			if err != nil {
				rt.Log("MR sidecar exited with warning: %v", err)
			}
			return nil
		}
	}, nil
}

func prepareSidecarSession(dir string) error {
	for _, sub := range []string{"raw", "parsed", "view", "logs", "outputs", "meta"} {
		if err := os.MkdirAll(filepath.Join(dir, sub), 0o755); err != nil {
			return err
		}
	}
	for _, name := range requiredRawFiles {
		file, err := os.OpenFile(filepath.Join(dir, "raw", name), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
		if err != nil {
			return err
		}
		_ = file.Close()
	}
	return nil
}

func hasCollectorOutput(dir string) bool {
	info, err := os.Stat(filepath.Join(dir, "raw", "collector_output_raw.log"))
	return err == nil && info.Size() > 0
}

func sidecarUTF8Env(env []string) []string {
	values := map[string]string{"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONLEGACYWINDOWSSTDIO": "0", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
	seen := map[string]bool{}
	result := make([]string, 0, len(env)+len(values))
	for _, item := range env {
		key := item
		if index := strings.IndexByte(item, '='); index >= 0 {
			key = item[:index]
		}
		if value, ok := values[key]; ok {
			result = append(result, key+"="+value)
			seen[key] = true
		} else {
			result = append(result, item)
		}
	}
	for key, value := range values {
		if !seen[key] {
			result = append(result, key+"="+value)
		}
	}
	return result
}

func sidecarStatus(dir string) map[string]any {
	b, err := os.ReadFile(filepath.Join(dir, "status.json"))
	if err != nil {
		return map[string]any{}
	}
	var result map[string]any
	if json.Unmarshal(b, &result) != nil {
		return map[string]any{}
	}
	return result
}
