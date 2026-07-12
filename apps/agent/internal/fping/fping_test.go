package fping

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"netconsole-agent/internal/core"
)

func TestBuildArgsAppliesPacketSizeAndModes(t *testing.T) {
	args, request, err := BuildArgs("fping.exe", Request{Targets: []string{"127.0.0.1", "example.com"}, IntervalMS: 10, TimeoutMS: 100, PacketSize: 1256, Count: 3, SourceAddress: "192.0.2.1"})
	if err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(args, " ")
	for _, expected := range []string{"-J", "-b 1256", "-p 10", "-t 100", "-c 3", "-S 192.0.2.1", "127.0.0.1", "example.com"} {
		if !strings.Contains(joined, expected) {
			t.Fatalf("missing %q in %q", expected, joined)
		}
	}
	if request.PacketSize != 1256 {
		t.Fatalf("packet_size=%d", request.PacketSize)
	}
	if _, _, err := BuildArgs("fping.exe", Request{Targets: []string{"127.0.0.1"}, Continuous: true, Count: 1}); err == nil {
		t.Fatal("continuous with count must fail")
	}
}

func TestRunnerWritesSamplesEventsAndResult(t *testing.T) {
	original := commandContext
	defer func() { commandContext = original }()
	commandContext = func(ctx context.Context, _ string, _ ...string) *exec.Cmd {
		cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=TestFpingHelperProcess")
		cmd.Env = append(os.Environ(), "NETCONSOLE_FPING_HELPER=1")
		return cmd
	}
	tool := filepath.Join(t.TempDir(), "fping.exe")
	if err := os.WriteFile(tool, []byte("fake"), 0o700); err != nil {
		t.Fatal(err)
	}
	runner, err := Runner(tool, Request{Targets: []string{"127.0.0.1"}, Count: 2, PacketSize: 1256})
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
	samples, err := os.ReadFile(filepath.Join(raw, "fping_samples.jsonl"))
	if err != nil || strings.Count(strings.TrimSpace(string(samples)), "\n")+1 != 2 || !strings.Contains(string(samples), `"packet_size":1256`) {
		t.Fatalf("samples=%q err=%v", string(samples), err)
	}
	page, err := readEventsForTest(filepath.Join(dir, "events.jsonl"))
	if err != nil || !strings.Contains(page, `"type":"sample"`) || !strings.Contains(page, `"type":"summary"`) {
		t.Fatalf("events=%q err=%v", page, err)
	}
	if _, err := os.Stat(filepath.Join(dir, "result.json")); err != nil {
		t.Fatal(err)
	}
}

func TestFpingHelperProcess(t *testing.T) {
	if os.Getenv("NETCONSOLE_FPING_HELPER") != "1" {
		return
	}
	_, _ = os.Stdout.Write([]byte("\xffinvalid\n"))
	_, _ = os.Stdout.WriteString("{\"resp\":{\"host\":\"127.0.0.1\",\"seq\":1,\"size\":1256,\"rtt\":0.2}}\n")
	_, _ = os.Stdout.WriteString("{\"timeout\":{\"host\":\"127.0.0.1\",\"seq\":2,\"size\":1256}}\n")
	_, _ = os.Stdout.WriteString("{\"summary\":{\"host\":\"127.0.0.1\"}}\n")
	os.Exit(0)
}

func readEventsForTest(path string) (string, error) {
	data, err := os.ReadFile(path)
	return string(data), err
}
