package fping

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
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
	"netconsole-agent/internal/util"
)

const (
	defaultIntervalMS = 100
	defaultTimeoutMS  = 100
	defaultPacketSize = 64
	defaultCount      = 20
	maxTargets        = 64
	maxCount          = 1_000_000
)

type Request struct {
	Targets       []string `json:"targets"`
	IntervalMS    int      `json:"interval_ms"`
	TimeoutMS     int      `json:"timeout_ms"`
	PacketSize    int      `json:"packet_size"`
	Count         int      `json:"count"`
	Continuous    bool     `json:"continuous"`
	SourceAddress string   `json:"source_address,omitempty"`
}

type ProtocolError struct {
	Code    string
	Message string
}

func (e *ProtocolError) Error() string       { return e.Message }
func (e *ProtocolError) TrafficCode() string { return e.Code }

type Sample struct {
	EventSequence int64          `json:"event_sequence"`
	Timestamp     string         `json:"timestamp"`
	Target        string         `json:"target"`
	ProbeSequence int            `json:"probe_sequence"`
	OK            bool           `json:"ok"`
	RTTMS         *float64       `json:"rtt_ms,omitempty"`
	PacketSize    int            `json:"packet_size"`
	Error         string         `json:"error,omitempty"`
	RawType       string         `json:"raw_type"`
	Raw           map[string]any `json:"raw"`
}

type targetStats struct {
	Sent, Received int
	Min, Sum, Max  float64
}

var hostnamePattern = regexp.MustCompile(`(?i)^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*$`)

func BuildArgs(tool string, request Request) ([]string, Request, error) {
	normalized, err := normalize(request)
	if err != nil {
		return nil, Request{}, err
	}
	args := []string{tool, "-J", "-b", strconv.Itoa(normalized.PacketSize), "-p", strconv.Itoa(normalized.IntervalMS), "-t", strconv.Itoa(normalized.TimeoutMS)}
	if normalized.Continuous {
		args = append(args, "-l")
	} else {
		args = append(args, "-c", strconv.Itoa(normalized.Count))
	}
	if normalized.SourceAddress != "" {
		args = append(args, "-S", normalized.SourceAddress)
	}
	args = append(args, normalized.Targets...)
	return args, normalized, nil
}

func Runner(tool string, request Request) (core.Runner, error) {
	if info, err := os.Stat(tool); err != nil || info.IsDir() {
		return nil, &ProtocolError{Code: "AGENT_TRAFFIC_TOOL_NOT_FOUND", Message: "未找到可执行的 fping 工具"}
	}
	args, normalized, err := BuildArgs(tool, request)
	if err != nil {
		return nil, err
	}
	return func(rt *core.Runtime) (runErr error) {
		rawPath := filepath.Join(rt.RawDir, "fping_raw.log")
		samplePath := filepath.Join(rt.RawDir, "fping_samples.jsonl")
		summaryPath := filepath.Join(rt.RawDir, "final_summary.json")
		rawFile, err := os.OpenFile(rawPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
		if err != nil {
			return err
		}
		defer rawFile.Close()
		sampleFile, err := os.OpenFile(samplePath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
		if err != nil {
			return err
		}
		defer sampleFile.Close()

		collector := newCollector(rt, rawFile, sampleFile, normalized)
		defer func() {
			summary := collector.summary()
			if err := util.WriteJSONAtomic(summaryPath, summary, 0o600); runErr == nil && err != nil {
				runErr = err
			}
			_, _ = rt.Emit("summary", "fping", summary)
			artifacts := []core.Artifact{
				{Name: "fping_raw.log", Kind: "raw"},
				{Name: "fping_samples.jsonl", Kind: "samples"},
				{Name: "final_summary.json", Kind: "summary"},
			}
			if err := rt.WriteResult(summary, artifacts); runErr == nil && err != nil {
				runErr = err
			}
		}()

		cmd := commandContext(rt.Ctx, tool, args[1:]...)
		cmd.Dir = filepath.Dir(tool)
		prepareCommand(cmd)
		stdout, err := cmd.StdoutPipe()
		if err != nil {
			return &ProtocolError{Code: "AGENT_TRAFFIC_PROCESS_START_FAILED", Message: "创建 fping stdout 管道失败"}
		}
		stderr, err := cmd.StderrPipe()
		if err != nil {
			return &ProtocolError{Code: "AGENT_TRAFFIC_PROCESS_START_FAILED", Message: "创建 fping stderr 管道失败"}
		}
		if err := cmd.Start(); err != nil {
			rt.Log("fping 启动失败: %v", err)
			return &ProtocolError{Code: "AGENT_TRAFFIC_PROCESS_START_FAILED", Message: "fping 启动失败"}
		}
		var streams sync.WaitGroup
		streams.Add(2)
		go func() { defer streams.Done(); collector.consume(stdout, "stdout") }()
		go func() { defer streams.Done(); collector.consume(stderr, "stderr") }()
		streams.Wait()
		waitErr := cmd.Wait()
		if collector.err != nil {
			rt.Log("fping 输出读取失败: %v", collector.err)
			return &ProtocolError{Code: "AGENT_TRAFFIC_OUTPUT_READ_FAILED", Message: "读取 fping 输出失败"}
		}
		if rt.Ctx.Err() != nil {
			return context.Canceled
		}
		if waitErr != nil {
			rt.Log("fping 进程异常退出: %v", waitErr)
			return &ProtocolError{Code: "AGENT_TRAFFIC_PROCESS_FAILED", Message: "fping 进程异常退出"}
		}
		return nil
	}, nil
}

var commandContext = exec.CommandContext

type collector struct {
	rt         *core.Runtime
	rawFile    *os.File
	sampleFile *os.File
	request    Request
	mu         sync.Mutex
	stats      map[string]*targetStats
	samples    int
	err        error
}

func newCollector(rt *core.Runtime, rawFile, sampleFile *os.File, request Request) *collector {
	stats := make(map[string]*targetStats, len(request.Targets))
	for _, target := range request.Targets {
		stats[target] = &targetStats{}
	}
	return &collector{rt: rt, rawFile: rawFile, sampleFile: sampleFile, request: request, stats: stats}
}

func (c *collector) consume(stream interface{ Read([]byte) (int, error) }, source string) {
	scanner := bufio.NewScanner(stream)
	scanner.Buffer(make([]byte, 64*1024), 4*1024*1024)
	for scanner.Scan() {
		line := strings.ToValidUTF8(scanner.Text(), "�")
		c.mu.Lock()
		if c.err == nil {
			_, c.err = fmt.Fprintf(c.rawFile, "[%s] [%s] %s\n", time.Now().UTC().Format(time.RFC3339Nano), source, line)
		}
		c.mu.Unlock()
		_, _ = c.rt.Emit(source, "fping", map[string]any{"line": line})
		c.consumeJSON(line)
	}
	if err := scanner.Err(); err != nil {
		c.mu.Lock()
		if c.err == nil {
			c.err = err
		}
		c.mu.Unlock()
	}
}

func (c *collector) consumeJSON(line string) {
	var raw map[string]any
	if json.Unmarshal([]byte(line), &raw) != nil {
		return
	}
	sample, eventType := sampleFromRaw(raw, c.request.PacketSize)
	if eventType == "" {
		return
	}
	payload := samplePayload(sample)
	event, err := c.rt.Emit(eventType, "fping", payload)
	if err != nil {
		c.mu.Lock()
		if c.err == nil {
			c.err = err
		}
		c.mu.Unlock()
		return
	}
	if eventType != "sample" {
		return
	}
	sample.EventSequence = event.Sequence
	sample.Timestamp = event.Timestamp
	data, err := json.Marshal(sample)
	if err != nil {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.err == nil {
		_, c.err = c.sampleFile.Write(append(data, '\n'))
	}
	c.samples++
	stats := c.stats[sample.Target]
	if stats == nil {
		stats = &targetStats{}
		c.stats[sample.Target] = stats
	}
	stats.Sent++
	if sample.OK && sample.RTTMS != nil {
		stats.Received++
		stats.Sum += *sample.RTTMS
		if stats.Min == 0 || *sample.RTTMS < stats.Min {
			stats.Min = *sample.RTTMS
		}
		if *sample.RTTMS > stats.Max {
			stats.Max = *sample.RTTMS
		}
	}
}

func (c *collector) summary() map[string]any {
	c.mu.Lock()
	defer c.mu.Unlock()
	targets := map[string]any{}
	totalSent, totalReceived := 0, 0
	for target, stats := range c.stats {
		loss, average := 0.0, 0.0
		if stats.Sent > 0 {
			loss = float64(stats.Sent-stats.Received) * 100 / float64(stats.Sent)
		}
		if stats.Received > 0 {
			average = stats.Sum / float64(stats.Received)
		}
		targets[target] = map[string]any{
			"sent": stats.Sent, "received": stats.Received, "loss_percent": loss,
			"rtt_min_ms": stats.Min, "rtt_avg_ms": average, "rtt_max_ms": stats.Max,
		}
		totalSent += stats.Sent
		totalReceived += stats.Received
	}
	loss := 0.0
	if totalSent > 0 {
		loss = float64(totalSent-totalReceived) * 100 / float64(totalSent)
	}
	return map[string]any{
		"target_count": len(c.stats), "samples": c.samples, "sent": totalSent,
		"received": totalReceived, "loss_percent": loss, "targets": targets,
	}
}

func normalize(request Request) (Request, error) {
	if len(request.Targets) == 0 || len(request.Targets) > maxTargets {
		return Request{}, invalid("targets 数量必须在 1-%d", maxTargets)
	}
	seen := map[string]bool{}
	targets := make([]string, len(request.Targets))
	for index, value := range request.Targets {
		target := strings.TrimSpace(value)
		if !validTarget(target) {
			return Request{}, invalid("目标地址无效: %s", target)
		}
		if seen[strings.ToLower(target)] {
			return Request{}, invalid("目标地址重复: %s", target)
		}
		seen[strings.ToLower(target)] = true
		targets[index] = target
	}
	request.Targets = targets
	if request.IntervalMS == 0 {
		request.IntervalMS = defaultIntervalMS
	}
	if request.TimeoutMS == 0 {
		request.TimeoutMS = defaultTimeoutMS
	}
	if request.PacketSize == 0 {
		request.PacketSize = defaultPacketSize
	}
	if request.IntervalMS < 1 || request.IntervalMS > 60_000 || request.TimeoutMS < 1 || request.TimeoutMS > 60_000 {
		return Request{}, invalid("interval_ms 和 timeout_ms 必须在 1-60000 之间")
	}
	if request.PacketSize < 1 || request.PacketSize > 65_507 {
		return Request{}, invalid("packet_size 必须在 1-65507 之间")
	}
	if request.Continuous && request.Count != 0 {
		return Request{}, invalid("continuous=true 时 count 必须为 0")
	}
	if !request.Continuous && request.Count == 0 {
		request.Count = defaultCount
	}
	if request.Count < 0 || request.Count > maxCount {
		return Request{}, invalid("count 必须在 0-%d 之间", maxCount)
	}
	if request.SourceAddress != "" && net.ParseIP(request.SourceAddress) == nil {
		return Request{}, invalid("source_address 必须是合法 IP 地址")
	}
	return request, nil
}

func validTarget(value string) bool {
	return value != "" && len(value) <= 253 && (net.ParseIP(value) != nil || hostnamePattern.MatchString(value))
}

func invalid(format string, args ...any) error {
	return &ProtocolError{Code: "AGENT_TRAFFIC_INVALID_CONFIG", Message: fmt.Sprintf(format, args...)}
}

func sampleFromRaw(raw map[string]any, packetSize int) (Sample, string) {
	for _, rawType := range []string{"resp", "timeout", "unreachable"} {
		value, ok := raw[rawType].(map[string]any)
		if !ok {
			continue
		}
		target := stringValue(value, "host", "target", "ip")
		if target == "" {
			return Sample{}, ""
		}
		sequence := intValue(value, "seq", "sequence")
		size := intValue(value, "size", "bytes")
		if size <= 0 {
			size = packetSize
		}
		sample := Sample{Target: target, ProbeSequence: sequence, PacketSize: size, RawType: rawType, Raw: raw}
		if rawType == "resp" {
			if rtt, ok := floatValue(value, "rtt", "rtt_ms"); ok {
				sample.OK = true
				sample.RTTMS = &rtt
			}
		} else {
			sample.Error = rawType
		}
		return sample, "sample"
	}
	if _, ok := raw["summary"].(map[string]any); ok {
		return Sample{RawType: "summary", Raw: raw}, "summary"
	}
	return Sample{}, ""
}

func samplePayload(sample Sample) map[string]any {
	payload := map[string]any{
		"target": sample.Target, "probe_sequence": sample.ProbeSequence, "ok": sample.OK,
		"packet_size": sample.PacketSize, "error": sample.Error, "raw_type": sample.RawType, "raw": sample.Raw,
	}
	if sample.RTTMS != nil {
		payload["rtt_ms"] = *sample.RTTMS
	}
	return payload
}

func stringValue(value map[string]any, keys ...string) string {
	for _, key := range keys {
		if text, ok := value[key].(string); ok && text != "" {
			return text
		}
	}
	return ""
}

func intValue(value map[string]any, keys ...string) int {
	for _, key := range keys {
		if number, ok := value[key].(float64); ok {
			return int(number)
		}
	}
	return 0
}

func floatValue(value map[string]any, keys ...string) (float64, bool) {
	for _, key := range keys {
		if number, ok := value[key].(float64); ok {
			return number, true
		}
	}
	return 0, false
}
