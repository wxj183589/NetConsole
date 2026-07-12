package pingprobe

import (
	"context"
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"netconsole-agent/internal/core"
)

func TestRunnerWritesEventsAndSummary(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			_ = conn.Close()
		}
	}()
	port, _ := strconv.Atoi(strings.Split(listener.Addr().String(), ":")[1])
	runner, err := Runner(Request{Targets: []string{"127.0.0.1"}, IntervalMS: 1, TimeoutMS: 100, PacketSize: 64, Count: 2, TCPPort: port}, 200, 500, 64, 80, 16)
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
	lines, err := os.ReadFile(filepath.Join(raw, "ping_probe_events.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Count(strings.TrimSpace(string(lines)), "\n") + 1; got != 2 {
		t.Fatalf("events=%d", got)
	}
	var summary map[string]any
	b, err := os.ReadFile(filepath.Join(raw, "ping_probe_summary.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(b, &summary); err != nil {
		t.Fatal(err)
	}
}
