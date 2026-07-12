package iperf

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"netconsole-agent/internal/core"
)

func TestLastMeasuredMbps(t *testing.T) {
	path := filepath.Join(t.TempDir(), "iperf.log")
	text := "[  5] 0.00-1.00 sec  50.0 MBytes  400 Mbits/sec\n[  5] 0.00-2.00 sec  1.20 GBytes  5.15 Gbits/sec receiver\n"
	if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	value, found := lastMeasuredMbps(path)
	if !found || value != 5150 {
		t.Fatalf("value=%v found=%v", value, found)
	}
}

func TestTypedClientArgsAndIncrementalEvents(t *testing.T) {
	original := commandContext
	defer func() { commandContext = original }()
	var captured []string
	commandContext = func(ctx context.Context, _ string, args ...string) *exec.Cmd {
		captured = append([]string(nil), args...)
		cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=TestIperfHelperProcess")
		cmd.Env = append(os.Environ(), "NETCONSOLE_IPERF_HELPER=1")
		return cmd
	}
	tool := filepath.Join(t.TempDir(), "iperf3.exe")
	if err := os.WriteFile(tool, []byte("fake"), 0o700); err != nil {
		t.Fatal(err)
	}
	runner, err := ClientRunner(tool, ClientRequest{
		ServerHost: "127.0.0.1", Protocol: "udp", DurationSec: 10, Parallel: 2,
		BandwidthMbps: 100, Bidirectional: true, ReportInterval: 0.5,
		UDPPacketLength: 1400, ConnectTimeoutMS: 2000,
	})
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	raw := filepath.Join(dir, "raw")
	if err := os.Mkdir(raw, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := runner(&core.Runtime{TaskID: "test", Dir: dir, RawDir: raw, Ctx: context.Background()}); err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(captured, " ")
	for _, expected := range []string{"-u", "-b 100M", "--bidir", "-i 0.5", "-l 1400", "--connect-timeout 2000"} {
		if !strings.Contains(joined, expected) {
			t.Fatalf("missing %q in %q", expected, joined)
		}
	}
	events, err := os.ReadFile(filepath.Join(dir, "events.jsonl"))
	if err != nil || !strings.Contains(string(events), `"type":"stdout"`) || !strings.Contains(string(events), `"code":"server_busy"`) {
		t.Fatalf("events=%q err=%v", string(events), err)
	}
	if _, err := os.Stat(filepath.Join(dir, "result.json")); err != nil {
		t.Fatal(err)
	}
	if _, err := ClientRunner(tool, ClientRequest{ServerHost: "bad\nhost"}); err == nil {
		t.Fatal("invalid server_host must fail")
	}
	if _, err := ServerRunner(tool, ServerRequest{BindAddress: "not-an-ip"}); err == nil {
		t.Fatal("invalid bind_address must fail")
	}
}

func TestIperfHelperProcess(t *testing.T) {
	if os.Getenv("NETCONSOLE_IPERF_HELPER") != "1" {
		return
	}
	_, _ = os.Stdout.WriteString("[  5] 0.00-1.00 sec 10 MBytes 80 Mbits/sec\n")
	_, _ = os.Stderr.WriteString("iperf3: error - the server is busy running a test\n")
	os.Exit(0)
}

func TestRejectsRoleOverrideInExtraArgs(t *testing.T) {
	if err := validateExtraArgs([]string{"--logfile", "other.log"}); err == nil {
		t.Fatal("expected blocked logfile")
	}
	if err := validateExtraArgs([]string{"--logfile=other.log"}); err == nil {
		t.Fatal("expected blocked logfile assignment")
	}
	if err := validateExtraArgs([]string{"--pidfile=other.pid"}); err == nil {
		t.Fatal("expected blocked pidfile assignment")
	}
	if err := validateExtraArgs([]string{"--title", "bad\nline"}); err == nil {
		t.Fatal("expected blocked control character")
	}
	if err := validateExtraArgs([]string{"--connect-timeout", "1000"}); err != nil {
		t.Fatal(err)
	}
}

func TestClassifiesCommonIperfErrors(t *testing.T) {
	for line, expected := range map[string]string{
		"the server is busy running a test":               "server_busy",
		"unable to connect to server: Connection refused": "connection_refused",
		"bind failed: Address already in use":             "address_in_use",
	} {
		if actual := classifyError(line); actual != expected {
			t.Fatalf("line=%q actual=%q expected=%q", line, actual, expected)
		}
	}
}
