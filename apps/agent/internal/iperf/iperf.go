package iperf

import (
	"bufio"
	"context"
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
	Bind           string  `json:"bind"`
	BindAddress    string  `json:"bind_address,omitempty"`
	Port           int     `json:"port"`
	Protocol       string  `json:"protocol"`
	ReportInterval float64 `json:"report_interval,omitempty"`
	OneOff         bool    `json:"one_off,omitempty"`
	// Deprecated: 仅为旧 Agent 客户端兼容保留；新客户端不得发送任意附加参数。
	ExtraArgs []string `json:"extra_args,omitempty"`
}

type ClientRequest struct {
	ServerHost       string  `json:"server_host"`
	ServerPort       int     `json:"server_port"`
	Protocol         string  `json:"protocol"`
	DurationSec      int     `json:"duration_sec"`
	Parallel         int     `json:"parallel"`
	BandwidthMbps    float64 `json:"bandwidth_mbps"`
	Reverse          bool    `json:"reverse"`
	ThresholdMbps    float64 `json:"threshold_mbps"`
	Bidirectional    bool    `json:"bidirectional,omitempty"`
	ReportInterval   float64 `json:"report_interval,omitempty"`
	UDPPacketLength  int     `json:"udp_packet_length,omitempty"`
	TCPBlockSize     int     `json:"tcp_block_size,omitempty"`
	ConnectTimeoutMS int     `json:"connect_timeout,omitempty"`
	// Deprecated: 仅为旧 Agent 客户端兼容保留；新客户端不得发送任意附加参数。
	ExtraArgs []string `json:"extra_args,omitempty"`
}

type ProtocolError struct {
	Code    string
	Message string
}

func (e *ProtocolError) Error() string       { return e.Message }
func (e *ProtocolError) TrafficCode() string { return e.Code }

func ValidateTool(path string) error {
	st, err := os.Stat(path)
	if err != nil {
		return &ProtocolError{Code: "AGENT_TRAFFIC_TOOL_NOT_FOUND", Message: "未找到 iperf3.exe"}
	}
	if st.IsDir() {
		return &ProtocolError{Code: "AGENT_TRAFFIC_TOOL_NOT_FOUND", Message: "iperf3 路径不是文件"}
	}
	return nil
}

func ServerRunner(tool string, request ServerRequest) (core.Runner, error) {
	if err := ValidateTool(tool); err != nil {
		return nil, err
	}
	if request.BindAddress != "" {
		request.Bind = request.BindAddress
	}
	if request.Bind == "" {
		request.Bind = "0.0.0.0"
	}
	if net.ParseIP(request.Bind) == nil {
		return nil, invalid("bind_address 必须是合法 IP 地址")
	}
	if request.Port == 0 {
		request.Port = 5201
	}
	if request.Port < 1 || request.Port > 65535 {
		return nil, invalid("iperf server 端口必须在 1-65535")
	}
	if err := validateExtraArgs(request.ExtraArgs); err != nil {
		return nil, err
	}
	if request.ReportInterval < 0.1 && request.ReportInterval != 0 || request.ReportInterval > 60 {
		return nil, invalid("report_interval 必须在 0.1-60 秒之间")
	}
	if err := checkPort(request.Bind, request.Port); err != nil {
		return nil, err
	}
	args := []string{"-s", "-B", request.Bind, "-p", strconv.Itoa(request.Port), "--forceflush"}
	if request.ReportInterval > 0 {
		args = append(args, "-i", formatSeconds(request.ReportInterval))
	}
	if request.OneOff {
		args = append(args, "-1")
	}
	args = append(args, request.ExtraArgs...)
	return commandRunner(tool, args, 0, "server"), nil
}

func ClientRunner(tool string, request ClientRequest) (core.Runner, error) {
	if err := ValidateTool(tool); err != nil {
		return nil, err
	}
	request.ServerHost = strings.TrimSpace(request.ServerHost)
	if !validHost(request.ServerHost) {
		return nil, invalid("server_host 必须是合法 IP 或主机名")
	}
	if request.ServerPort == 0 {
		request.ServerPort = 5201
	}
	if request.ServerPort < 1 || request.ServerPort > 65535 {
		return nil, invalid("server_port 必须在 1-65535")
	}
	if request.Parallel <= 0 {
		request.Parallel = 1
	}
	if request.DurationSec == 0 {
		request.DurationSec = 10
	}
	protocol := strings.ToLower(strings.TrimSpace(request.Protocol))
	if protocol == "" {
		protocol = "tcp"
	}
	if protocol != "tcp" && protocol != "udp" {
		return nil, invalid("protocol 只支持 tcp 或 udp")
	}
	if request.DurationSec < 1 || request.DurationSec > 86_400 {
		return nil, invalid("duration_sec 必须在 1-86400 秒之间")
	}
	if request.Parallel < 1 || request.Parallel > 128 {
		return nil, invalid("parallel 必须在 1-128 之间")
	}
	if request.BandwidthMbps < 0 || request.BandwidthMbps > 1_000_000 {
		return nil, invalid("bandwidth_mbps 超出允许范围")
	}
	if request.Reverse && request.Bidirectional {
		return nil, invalid("reverse 与 bidirectional 不能同时启用")
	}
	if request.ReportInterval < 0.1 && request.ReportInterval != 0 || request.ReportInterval > 60 {
		return nil, invalid("report_interval 必须在 0.1-60 秒之间")
	}
	if request.UDPPacketLength != 0 && (protocol != "udp" || request.UDPPacketLength < 1 || request.UDPPacketLength > 65_507) {
		return nil, invalid("udp_packet_length 仅适用于 UDP，且必须在 1-65507 之间")
	}
	if request.TCPBlockSize != 0 && (protocol != "tcp" || request.TCPBlockSize < 1 || request.TCPBlockSize > 16*1024*1024) {
		return nil, invalid("tcp_block_size 仅适用于 TCP，且必须在 1-16777216 之间")
	}
	if request.ConnectTimeoutMS != 0 && (request.ConnectTimeoutMS < 100 || request.ConnectTimeoutMS > 60_000) {
		return nil, invalid("connect_timeout 必须在 100-60000 毫秒之间")
	}
	if err := validateExtraArgs(request.ExtraArgs); err != nil {
		return nil, err
	}
	args := []string{"-c", request.ServerHost, "-p", strconv.Itoa(request.ServerPort), "-P", strconv.Itoa(request.Parallel), "--forceflush"}
	args = append(args, "-t", strconv.Itoa(request.DurationSec))
	if request.ReportInterval > 0 {
		args = append(args, "-i", formatSeconds(request.ReportInterval))
	}
	if request.ConnectTimeoutMS > 0 {
		args = append(args, "--connect-timeout", strconv.Itoa(request.ConnectTimeoutMS))
	}
	if protocol == "udp" {
		args = append(args, "-u")
		if request.BandwidthMbps > 0 {
			args = append(args, "-b", fmt.Sprintf("%gM", request.BandwidthMbps))
		}
		if request.UDPPacketLength > 0 {
			args = append(args, "-l", strconv.Itoa(request.UDPPacketLength))
		}
	} else if request.TCPBlockSize > 0 {
		args = append(args, "-l", strconv.Itoa(request.TCPBlockSize))
	}
	if request.Reverse {
		args = append(args, "-R")
	} else if request.Bidirectional {
		args = append(args, "--bidir")
	}
	args = append(args, request.ExtraArgs...)
	return commandRunner(tool, args, request.ThresholdMbps, "client"), nil
}

func commandRunner(tool string, args []string, thresholdMbps float64, mode string) core.Runner {
	return func(rt *core.Runtime) error {
		logPath := filepath.Join(rt.RawDir, "iperf_raw.log")
		f, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
		if err != nil {
			return err
		}
		defer f.Close()
		rt.Log("启动 iperf3 args=%s", strings.Join(redactArgs(args), " "))
		_, _ = fmt.Fprintf(f, "[%s] iperf3 %s\n", time.Now().Format(time.RFC3339Nano), strings.Join(redactArgs(args), " "))
		exitCode := -1
		defer func() {
			summary := map[string]any{"mode": mode, "process_exit_code": exitCode}
			_, _ = rt.Emit("summary", "iperf", summary)
			_ = rt.WriteResult(
				summary,
				[]core.Artifact{{Name: "iperf_raw.log", Kind: "raw"}},
			)
		}()
		cmd := commandContext(rt.Ctx, tool, args...)
		cmd.Dir = filepath.Dir(tool)
		prepareCommand(cmd)
		stdout, err := cmd.StdoutPipe()
		if err != nil {
			return &ProtocolError{Code: "AGENT_TRAFFIC_PROCESS_START_FAILED", Message: "创建 iperf3 stdout 管道失败"}
		}
		stderr, err := cmd.StderrPipe()
		if err != nil {
			return &ProtocolError{Code: "AGENT_TRAFFIC_PROCESS_START_FAILED", Message: "创建 iperf3 stderr 管道失败"}
		}
		if err := cmd.Start(); err != nil {
			_, _ = fmt.Fprintf(f, "[%s] ERROR iperf3 启动失败: %v\n", time.Now().Format(time.RFC3339Nano), err)
			rt.Log("iperf3 启动失败: %v", err)
			return &ProtocolError{Code: "AGENT_TRAFFIC_PROCESS_START_FAILED", Message: "iperf3 启动失败"}
		}
		writer := &lockedWriter{writer: f}
		var copies sync.WaitGroup
		streamErrors := make(chan error, 2)
		copies.Add(2)
		go func() { defer copies.Done(); streamErrors <- streamOutput(rt, writer, stdout, "stdout") }()
		go func() { defer copies.Done(); streamErrors <- streamOutput(rt, writer, stderr, "stderr") }()
		copies.Wait()
		close(streamErrors)
		err = cmd.Wait()
		if cmd.ProcessState != nil {
			exitCode = cmd.ProcessState.ExitCode()
		}
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
		for streamErr := range streamErrors {
			if streamErr != nil {
				rt.Log("iperf3 输出读取失败: %v", streamErr)
				return &ProtocolError{Code: "AGENT_TRAFFIC_OUTPUT_READ_FAILED", Message: "读取 iperf3 输出失败"}
			}
		}
		if err != nil {
			rt.Log("iperf3 进程异常退出: %v", err)
			return &ProtocolError{Code: "AGENT_TRAFFIC_PROCESS_FAILED", Message: "iperf3 进程异常退出"}
		}
		return nil
	}
}

var commandContext = exec.CommandContext

func streamOutput(rt *core.Runtime, writer io.Writer, reader io.Reader, source string) error {
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 64*1024), 4*1024*1024)
	for scanner.Scan() {
		line := strings.ToValidUTF8(scanner.Text(), "�")
		_, _ = fmt.Fprintln(writer, line)
		_, _ = rt.Emit(source, "iperf", map[string]any{"line": line})
		if code := classifyError(line); code != "" {
			_, _ = rt.Emit("error", "iperf", map[string]any{"code": code, "message": line})
		}
	}
	if err := scanner.Err(); err != nil {
		_, _ = rt.Emit("error", "iperf", map[string]any{"code": "AGENT_TRAFFIC_OUTPUT_READ_FAILED", "message": err.Error()})
		return err
	}
	return nil
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
var hostnamePattern = regexp.MustCompile(`(?i)^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*$`)

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
		return &ProtocolError{Code: "AGENT_TRAFFIC_PORT_IN_USE", Message: fmt.Sprintf("端口已占用或无法监听 %s:%d", bind, port)}
	}
	return ln.Close()
}

func invalid(message string) error {
	return &ProtocolError{Code: "AGENT_TRAFFIC_INVALID_CONFIG", Message: message}
}

func validHost(value string) bool {
	return value != "" && len(value) <= 253 && (net.ParseIP(value) != nil || hostnamePattern.MatchString(value))
}

func formatSeconds(value float64) string {
	return strconv.FormatFloat(value, 'f', -1, 64)
}

func classifyError(line string) string {
	text := strings.ToLower(line)
	switch {
	case strings.Contains(text, "server is busy"):
		return "server_busy"
	case strings.Contains(text, "connection refused") || strings.Contains(text, "unable to connect"):
		return "connection_refused"
	case strings.Contains(text, "address already in use"):
		return "address_in_use"
	}
	return ""
}

func redactArgs(args []string) []string { return append([]string(nil), args...) }

func validateExtraArgs(args []string) error {
	blocked := map[string]bool{
		"-s": true, "--server": true, "-c": true, "--client": true,
		"--logfile": true, "--pidfile": true, "-D": true, "--daemon": true,
	}
	for _, arg := range args {
		if strings.ContainsAny(arg, "\x00\r\n") {
			return invalid("extra_args 不允许包含控制字符")
		}
		name := strings.SplitN(arg, "=", 2)[0]
		if blocked[name] {
			return invalid("extra_args 不允许覆盖任务角色、后台模式或日志路径: " + arg)
		}
	}
	return nil
}
