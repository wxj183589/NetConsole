package pingprobe

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"netconsole-agent/internal/core"
	"netconsole-agent/internal/util"
)

type Request struct {
	Targets    []string `json:"targets"`
	IntervalMS int      `json:"interval_ms"`
	TimeoutMS  int      `json:"timeout_ms"`
	PacketSize int      `json:"packet_size"`
	Count      int      `json:"count"`
	TCPPort    int      `json:"tcp_port,omitempty"`
}

type event struct {
	TS     string  `json:"ts"`
	Target string  `json:"target"`
	Seq    int     `json:"seq"`
	OK     bool    `json:"ok"`
	RTTMS  float64 `json:"rtt_ms,omitempty"`
	Bytes  int     `json:"bytes"`
	Mode   string  `json:"mode"`
	Error  string  `json:"error,omitempty"`
}

type stats struct {
	Sent, Received int
	Min, Sum, Max  float64
}

func Runner(request Request, defaultInterval, defaultTimeout, defaultSize, defaultPort, maxTargets int) (core.Runner, error) {
	if len(request.Targets) == 0 {
		return nil, errors.New("ping_probe targets 不能为空")
	}
	if len(request.Targets) > maxTargets {
		return nil, fmt.Errorf("目标数量超过上限 %d", maxTargets)
	}
	seen := map[string]bool{}
	for i := range request.Targets {
		request.Targets[i] = strings.TrimSpace(request.Targets[i])
		if request.Targets[i] == "" {
			return nil, errors.New("ping_probe target 不能为空")
		}
		if seen[request.Targets[i]] {
			return nil, fmt.Errorf("目标重复: %s", request.Targets[i])
		}
		seen[request.Targets[i]] = true
	}
	if request.IntervalMS <= 0 {
		request.IntervalMS = defaultInterval
	}
	if request.TimeoutMS <= 0 {
		request.TimeoutMS = defaultTimeout
	}
	if request.PacketSize <= 0 {
		request.PacketSize = defaultSize
	}
	if request.TCPPort <= 0 {
		request.TCPPort = defaultPort
	}
	if request.TCPPort < 1 || request.TCPPort > 65535 {
		return nil, errors.New("tcp_port 必须在 1-65535")
	}
	return func(rt *core.Runtime) error {
		path := filepath.Join(rt.RawDir, "ping_probe_events.jsonl")
		f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
		if err != nil {
			return err
		}
		defer f.Close()
		writer := bufio.NewWriter(f)
		defer writer.Flush()
		all := map[string]*stats{}
		for _, target := range request.Targets {
			all[target] = &stats{}
		}
		rt.Log("ping_probe 使用 TCP connect fallback，端口=%d", request.TCPPort)
		seq := 0
		for {
			if request.Count > 0 && seq >= request.Count {
				break
			}
			seq++
			events := probeAll(rt.Ctx, request.Targets, request.TCPPort, request.TimeoutMS, request.PacketSize, seq)
			for _, e := range events {
				b, _ := json.Marshal(e)
				_, _ = writer.Write(append(b, '\n'))
				_ = writer.Flush()
				s := all[e.Target]
				s.Sent++
				if e.OK {
					s.Received++
					s.Sum += e.RTTMS
					if s.Min == 0 || e.RTTMS < s.Min {
						s.Min = e.RTTMS
					}
					if e.RTTMS > s.Max {
						s.Max = e.RTTMS
					}
				}
			}
			select {
			case <-rt.Ctx.Done():
				return writeSummary(rt.RawDir, all)
			case <-time.After(time.Duration(request.IntervalMS) * time.Millisecond):
			}
		}
		return writeSummary(rt.RawDir, all)
	}, nil
}

func probeAll(ctx context.Context, targets []string, port, timeoutMS, size, seq int) []event {
	events := make([]event, len(targets))
	var wg sync.WaitGroup
	for i, target := range targets {
		i, target := i, target
		wg.Add(1)
		go func() {
			defer wg.Done()
			events[i] = probe(ctx, target, port, timeoutMS, size, seq)
		}()
	}
	wg.Wait()
	return events
}

func probe(ctx context.Context, target string, port, timeoutMS, size, seq int) event {
	start := time.Now()
	e := event{TS: start.Format(time.RFC3339Nano), Target: target, Seq: seq, Bytes: size, Mode: "tcp"}
	dialer := net.Dialer{Timeout: time.Duration(timeoutMS) * time.Millisecond}
	conn, err := dialer.DialContext(ctx, "tcp", net.JoinHostPort(target, strconv.Itoa(port)))
	if err != nil {
		e.Error = normalizeError(err)
		return e
	}
	e.OK = true
	e.RTTMS = float64(time.Since(start).Microseconds()) / 1000
	_ = conn.Close()
	return e
}

func writeSummary(rawDir string, all map[string]*stats) error {
	targets := map[string]any{}
	for target, s := range all {
		loss := 0.0
		avg := 0.0
		if s.Sent > 0 {
			loss = float64(s.Sent-s.Received) * 100 / float64(s.Sent)
		}
		if s.Received > 0 {
			avg = s.Sum / float64(s.Received)
		}
		targets[target] = map[string]any{"sent": s.Sent, "received": s.Received, "loss_percent": loss, "rtt_min_ms": s.Min, "rtt_avg_ms": avg, "rtt_max_ms": s.Max, "mode": "tcp"}
	}
	return util.WriteJSONAtomic(filepath.Join(rawDir, "ping_probe_summary.json"), map[string]any{"targets": targets}, 0o600)
}

func normalizeError(err error) string {
	if errors.Is(err, context.DeadlineExceeded) {
		return "timeout"
	}
	if ne, ok := err.(net.Error); ok && ne.Timeout() {
		return "timeout"
	}
	return err.Error()
}
