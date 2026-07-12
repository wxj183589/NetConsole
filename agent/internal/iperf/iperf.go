package iperf

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"netconsole-agent/internal/core"
)

type ServerRequest struct {
	Bind      string   `json:"bind"`
	Port      int      `json:"port"`
	Protocol  string   `json:"protocol"`
	ExtraArgs []string `json:"extra_args"`
}

type ClientRequest struct {
	ServerHost    string   `json:"server_host"`
	ServerPort    int      `json:"server_port"`
	Protocol      string   `json:"protocol"`
	DurationSec   int      `json:"duration_sec"`
	Parallel      int      `json:"parallel"`
	BandwidthMbps float64  `json:"bandwidth_mbps"`
	Reverse       bool     `json:"reverse"`
	ThresholdMbps float64  `json:"threshold_mbps"`
	ExtraArgs     []string `json:"extra_args"`
}

func ValidateTool(path string) error {
	st, err := os.Stat(path)
	if err != nil {
		return fmt.Errorf("未找到 iperf3.exe: %s", path)
	}
	if st.IsDir() {
		return fmt.Errorf("iperf3 路径不是文件: %s", path)
	}
	return nil
}

func ServerRunner(tool string, request ServerRequest) (core.Runner, error) {
	if err := ValidateTool(tool); err != nil {
		return nil, err
	}
	if request.Bind == "" {
		request.Bind = "0.0.0.0"
	}
	if request.Port == 0 {
		request.Port = 5201
	}
	if request.Port < 1 || request.Port > 65535 {
		return nil, errors.New("iperf server 端口必须在 1-65535")
	}
	if err := validateExtraArgs(request.ExtraArgs); err != nil {
		return nil, err
	}
	if err := checkPort(request.Bind, request.Port); err != nil {
		return nil, err
	}
	args := []string{"-s", "-B", request.Bind, "-p", strconv.Itoa(request.Port), "--forceflush"}
	args = append(args, request.ExtraArgs...)
	return commandRunner(tool, args, 0), nil
}

func ClientRunner(tool string, request ClientRequest) (core.Runner, error) {
	if err := ValidateTool(tool); err != nil {
		return nil, err
	}
	if strings.TrimSpace(request.ServerHost) == "" {
		return nil, errors.New("server_host 不能为空")
	}
	if request.ServerPort == 0 {
		request.ServerPort = 5201
	}
	if request.ServerPort < 1 || request.ServerPort > 65535 {
		return nil, errors.New("server_port 必须在 1-65535")
	}
	if request.Parallel <= 0 {
		request.Parallel = 1
	}
	if err := validateExtraArgs(request.ExtraArgs); err != nil {
		return nil, err
	}
	args := []string{"-c", request.ServerHost, "-p", strconv.Itoa(request.ServerPort), "-P", strconv.Itoa(request.Parallel), "--forceflush"}
	if request.DurationSec == 0 {
		args = append(args, "-t", "0")
	} else if request.DurationSec > 0 {
		args = append(args, "-t", strconv.Itoa(request.DurationSec))
	}
	if strings.EqualFold(request.Protocol, "udp") {
		args = append(args, "-u")
		if request.BandwidthMbps > 0 {
			args = append(args, "-b", fmt.Sprintf("%gM", request.BandwidthMbps))
		}
	}
	if request.Reverse {
		args = append(args, "-R")
	}
	args = append(args, request.ExtraArgs...)
	return commandRunner(tool, args, request.ThresholdMbps), nil
}

func commandRunner(tool string, args []string, thresholdMbps float64) core.Runner {
	return func(rt *core.Runtime) error {
		logPath := filepath.Join(rt.RawDir, "iperf_raw.log")
		f, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
		if err != nil {
			return err
		}
		defer f.Close()
		rt.Log("启动 iperf3 args=%s", strings.Join(redactArgs(args), " "))
		_, _ = fmt.Fprintf(f, "[%s] iperf3 %s\n", time.Now().Format(time.RFC3339Nano), strings.Join(redactArgs(args), " "))
		cmd := exec.CommandContext(rt.Ctx, tool, args...)
		cmd.Dir = filepath.Dir(tool)
		prepareCommand(cmd)
		stdout, err := cmd.StdoutPipe()
		if err != nil {
			return fmt.Errorf("创建 iperf3 stdout 管道失败: %w", err)
		}
		stderr, err := cmd.StderrPipe()
		if err != nil {
			return fmt.Errorf("创建 iperf3 stderr 管道失败: %w", err)
		}
		if err := cmd.Start(); err != nil {
			_, _ = fmt.Fprintf(f, "[%s] ERROR iperf3 启动失败: %v\n", time.Now().Format(time.RFC3339Nano), err)
			return fmt.Errorf("iperf3 启动失败: %w", err)
		}
		writer := &lockedWriter{writer: f}
		var copies sync.WaitGroup
		copies.Add(2)
		go func() { defer copies.Done(); _, _ = io.Copy(writer, stdout) }()
		go func() { defer copies.Done(); _, _ = io.Copy(writer, stderr) }()
		err = cmd.Wait()
		copies.Wait()
		if err != nil {
			_, _ = fmt.Fprintf(f, "\n[%s] iperf3 exit: %v\n", time.Now().Format(time.RFC3339Nano), err)
		}
		_ = f.Sync()
		if thresholdMbps > 0 {
			if measured, found := lastMeasuredMbps(logPath); found && measured < thresholdMbps {
				rt.Log("WARNING iPerf 吞吐低于阈值 measured_mbps=%.3f threshold_mbps=%.3f", measured, thresholdMbps)
			}
		}
		if rt.Ctx.Err() != nil {
			return context.Canceled
		}
		if err != nil {
			return fmt.Errorf("iperf3 执行失败: %w", err)
		}
		return nil
	}
}

type lockedWriter struct {
	mu     sync.Mutex
	writer io.Writer
}

func (w *lockedWriter) Write(data []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.writer.Write(data)
}

var bandwidthPattern = regexp.MustCompile(`(?i)([0-9]+(?:\.[0-9]+)?)\s*([KMG])bits/sec`)

func lastMeasuredMbps(path string) (float64, bool) {
	b, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}
	matches := bandwidthPattern.FindAllStringSubmatch(string(b), -1)
	if len(matches) == 0 {
		return 0, false
	}
	last := matches[len(matches)-1]
	value, err := strconv.ParseFloat(last[1], 64)
	if err != nil {
		return 0, false
	}
	switch strings.ToUpper(last[2]) {
	case "K":
		value /= 1000
	case "G":
		value *= 1000
	}
	return value, true
}

func checkPort(bind string, port int) error {
	ln, err := net.Listen("tcp", net.JoinHostPort(bind, strconv.Itoa(port)))
	if err != nil {
		return fmt.Errorf("端口已占用或无法监听 %s:%d: %w", bind, port, err)
	}
	return ln.Close()
}

func redactArgs(args []string) []string { return append([]string(nil), args...) }

func validateExtraArgs(args []string) error {
	blocked := map[string]bool{"-s": true, "--server": true, "-c": true, "--client": true, "--logfile": true, "-D": true, "--daemon": true}
	for _, arg := range args {
		if blocked[arg] {
			return fmt.Errorf("extra_args 不允许覆盖任务角色、后台模式或日志路径: %s", arg)
		}
	}
	return nil
}
