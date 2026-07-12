package mr

import (
	"bufio"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"golang.org/x/crypto/ssh"

	"netconsole-agent/internal/core"
	"netconsole-agent/internal/target"
)

func TestRunnerCollectsAllRawFilesAndStops(t *testing.T) {
	address, commands, stopServer := startFakeSSHServer(t)
	defer stopServer()
	host, portText, err := net.SplitHostPort(address)
	if err != nil {
		t.Fatal(err)
	}
	port, _ := strconv.Atoi(portText)
	runner, err := Runner(Request{
		Target:      target.Target{Name: "MR-Test", Host: host, Protocol: "ssh", Port: port, Username: "admin", Password: "pass"},
		IntervalSec: 1,
		Items:       Items{TerminalMonitor: true, ChannelBusy: true, APRadioStatistics: true, WirelessRSSI: true, WirelessStatus: true},
	})
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	rawDir := filepath.Join(dir, "raw")
	if err := os.Mkdir(rawDir, 0o755); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- runner(&core.Runtime{TaskID: "mr-test", Dir: dir, RawDir: rawDir, Ctx: ctx}) }()

	required := map[string]bool{
		"terminal monitor":                   false,
		"display ar5drv 1 channelbusy":       false,
		"display ar5drv 1 statistics":        false,
		"display ar5drv 1 client all rssi":   false,
		"display ar5drv 1 client all status": false,
	}
	deadline := time.After(3 * time.Second)
	for !allSeen(required) {
		select {
		case command := <-commands:
			if _, ok := required[command]; ok {
				required[command] = true
			}
		case <-deadline:
			t.Fatalf("missing commands: %#v", required)
		}
	}
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("runner error=%v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("MR runner did not stop")
	}
	for _, name := range []string{"terminal_monitor_raw.log", "channel_busy_raw.log", "ap_radio_statistics_raw.log", "wireless_rssi_raw.log", "wireless_status_raw.log"} {
		info, err := os.Stat(filepath.Join(rawDir, name))
		if err != nil || info.Size() == 0 {
			t.Fatalf("raw %s info=%v err=%v", name, info, err)
		}
	}
}

func allSeen(values map[string]bool) bool {
	for _, seen := range values {
		if !seen {
			return false
		}
	}
	return true
}

func startFakeSSHServer(t *testing.T) (string, <-chan string, func()) {
	t.Helper()
	_, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	signer, err := ssh.NewSignerFromKey(private)
	if err != nil {
		t.Fatal(err)
	}
	config := &ssh.ServerConfig{PasswordCallback: func(meta ssh.ConnMetadata, password []byte) (*ssh.Permissions, error) {
		if meta.User() != "admin" || string(password) != "pass" {
			return nil, fmt.Errorf("denied")
		}
		return nil, nil
	}}
	config.AddHostKey(signer)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	commands := make(chan string, 256)
	var once sync.Once
	stop := func() { once.Do(func() { _ = listener.Close() }) }
	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go serveSSHConnection(conn, config, commands)
		}
	}()
	return listener.Addr().String(), commands, stop
}

func serveSSHConnection(conn net.Conn, config *ssh.ServerConfig, commands chan<- string) {
	server, channels, requests, err := ssh.NewServerConn(conn, config)
	if err != nil {
		_ = conn.Close()
		return
	}
	defer server.Close()
	go ssh.DiscardRequests(requests)
	for incoming := range channels {
		if incoming.ChannelType() != "session" {
			_ = incoming.Reject(ssh.UnknownChannelType, "session only")
			continue
		}
		channel, requests, err := incoming.Accept()
		if err != nil {
			continue
		}
		go func() {
			defer channel.Close()
			started := false
			for request := range requests {
				switch request.Type {
				case "pty-req":
					_ = request.Reply(true, nil)
				case "shell":
					_ = request.Reply(true, nil)
					if !started {
						started = true
						go echoSSHCommands(channel, commands)
					}
				default:
					_ = request.Reply(false, nil)
				}
			}
		}()
	}
}

func echoSSHCommands(channel ssh.Channel, commands chan<- string) {
	scanner := bufio.NewScanner(channel)
	for scanner.Scan() {
		command := strings.TrimSpace(scanner.Text())
		if command == "" {
			continue
		}
		commands <- command
		_, _ = fmt.Fprintf(channel, "OK %s\r\n", command)
	}
}
