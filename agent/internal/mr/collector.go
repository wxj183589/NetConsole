package mr

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"golang.org/x/crypto/ssh"

	"netconsole-agent/internal/core"
	"netconsole-agent/internal/target"
)

type Items struct {
	TerminalMonitor   bool `json:"terminal_monitor"`
	ChannelBusy       bool `json:"channel_busy"`
	APRadioStatistics bool `json:"ap_radio_statistics"`
	WirelessRSSI      bool `json:"wireless_rssi"`
	WirelessStatus    bool `json:"wireless_status"`
}

type Request struct {
	TargetID          string        `json:"target_id,omitempty"`
	Target            target.Target `json:"target,omitempty"`
	IntervalSec       int           `json:"interval_sec"`
	Items             Items         `json:"items"`
	AutoPackageOnStop bool          `json:"auto_package_on_stop"`
}

func TestConnection(t target.Target, timeout time.Duration) error {
	if strings.EqualFold(t.Protocol, "local") {
		return nil
	}
	address := net.JoinHostPort(t.Host, strconv.Itoa(t.Port))
	if strings.EqualFold(t.Protocol, "telnet") {
		conn, err := net.DialTimeout("tcp", address, timeout)
		if err != nil {
			return fmt.Errorf("Telnet TCP 连接失败: %w", err)
		}
		return conn.Close()
	}
	if !strings.EqualFold(t.Protocol, "ssh") {
		return fmt.Errorf("不支持的协议: %s", t.Protocol)
	}
	client, err := ssh.Dial("tcp", address, sshConfig(t, timeout))
	if err != nil {
		return fmt.Errorf("SSH 登录失败: %w", err)
	}
	return client.Close()
}

func Runner(request Request) (core.Runner, error) {
	if !strings.EqualFold(request.Target.Protocol, "ssh") {
		return nil, errors.New("MR V1 仅支持 SSH，Telnet 尚未实现")
	}
	if request.Target.Host == "" || request.Target.Port <= 0 || request.Target.Username == "" {
		return nil, errors.New("MR SSH host、port、username 不能为空")
	}
	if request.IntervalSec <= 0 {
		request.IntervalSec = 3
	}
	if !request.Items.TerminalMonitor && !request.Items.ChannelBusy && !request.Items.APRadioStatistics && !request.Items.WirelessRSSI && !request.Items.WirelessStatus {
		return nil, errors.New("至少选择一个 MR 采集项")
	}
	return func(rt *core.Runtime) error {
		address := net.JoinHostPort(request.Target.Host, strconv.Itoa(request.Target.Port))
		client, err := ssh.Dial("tcp", address, sshConfig(request.Target, 10*time.Second))
		if err != nil {
			return fmt.Errorf("SSH 登录失败: %w", err)
		}
		defer client.Close()
		rt.Log("MR SSH 已连接 target=%s host=%s", request.Target.Name, request.Target.Host)
		ctx, cancel := context.WithCancel(rt.Ctx)
		defer cancel()
		var wg sync.WaitGroup
		errorsCh := make(chan error, 8)
		if request.Items.TerminalMonitor {
			wg.Add(1)
			go func() {
				defer wg.Done()
				if err := runTerminalMonitor(ctx, client, filepath.Join(rt.RawDir, "terminal_monitor_raw.log")); err != nil && ctx.Err() == nil {
					errorsCh <- err
				}
			}()
		}
		enabled := map[string]bool{"channel_busy": request.Items.ChannelBusy, "ap_radio_statistics": request.Items.APRadioStatistics, "wireless_rssi": request.Items.WirelessRSSI, "wireless_status": request.Items.WirelessStatus}
		for name, on := range enabled {
			if !on {
				continue
			}
			item := name
			wg.Add(1)
			go func() {
				defer wg.Done()
				if err := runPeriodic(ctx, client, item, time.Duration(request.IntervalSec)*time.Second, filepath.Join(rt.RawDir, rawNames[item])); err != nil && ctx.Err() == nil {
					errorsCh <- err
				}
			}()
		}
		select {
		case <-rt.Ctx.Done():
			cancel()
			_ = client.Close()
			wg.Wait()
			return context.Canceled
		case err := <-errorsCh:
			cancel()
			_ = client.Close()
			wg.Wait()
			return err
		}
	}, nil
}

func runTerminalMonitor(ctx context.Context, client *ssh.Client, path string) error {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer f.Close()
	session, err := client.NewSession()
	if err != nil {
		return fmt.Errorf("创建 terminal monitor 会话失败: %w", err)
	}
	defer session.Close()
	if err := session.RequestPty("vt100", 120, 40, ssh.TerminalModes{ssh.ECHO: 0}); err != nil {
		return err
	}
	session.Stdout, session.Stderr = f, f
	stdin, err := session.StdinPipe()
	if err != nil {
		return err
	}
	if err := session.Shell(); err != nil {
		return err
	}
	if err := writeCommands(stdin, terminalMonitorCommands); err != nil {
		return err
	}
	wait := make(chan error, 1)
	go func() { wait <- session.Wait() }()
	select {
	case <-ctx.Done():
		_, _ = io.WriteString(stdin, "\x03\nquit\n")
		return nil
	case err := <-wait:
		if err != nil {
			return fmt.Errorf("terminal monitor 会话中断: %w", err)
		}
		return errors.New("terminal monitor 会话意外结束")
	}
}

func runPeriodic(ctx context.Context, client *ssh.Client, item string, interval time.Duration, path string) error {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer f.Close()
	session, err := client.NewSession()
	if err != nil {
		return fmt.Errorf("创建 %s SSH 会话失败: %w", item, err)
	}
	defer session.Close()
	if err := session.RequestPty("vt100", 120, 40, ssh.TerminalModes{ssh.ECHO: 0}); err != nil {
		return err
	}
	session.Stdout, session.Stderr = f, f
	stdin, err := session.StdinPipe()
	if err != nil {
		return err
	}
	if err := session.Shell(); err != nil {
		return err
	}
	if err := writeCommands(stdin, probePrepareCommands); err != nil {
		return err
	}
	wait := make(chan error, 1)
	go func() { wait <- session.Wait() }()
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	runSample := func() error {
		if _, err := fmt.Fprintf(f, "\n[%s] >>> %s\n", time.Now().Format(time.RFC3339Nano), strings.Join(periodicCommands[item], " ; ")); err != nil {
			return err
		}
		return writeCommands(stdin, periodicCommands[item])
	}
	if err := runSample(); err != nil {
		return err
	}
	for {
		select {
		case <-ctx.Done():
			_, _ = io.WriteString(stdin, "\x03\nreturn\nquit\n")
			return nil
		case <-ticker.C:
			if err := runSample(); err != nil {
				return fmt.Errorf("%s 写入周期命令失败: %w", item, err)
			}
		case err := <-wait:
			if err != nil {
				return fmt.Errorf("%s SSH 会话中断: %w", item, err)
			}
			return fmt.Errorf("%s SSH 会话意外结束", item)
		}
	}
}

func writeCommands(w io.Writer, commands []string) error {
	for _, command := range commands {
		if _, err := io.WriteString(w, command+"\n"); err != nil {
			return err
		}
	}
	return nil
}

func sshConfig(t target.Target, timeout time.Duration) *ssh.ClientConfig {
	return &ssh.ClientConfig{User: t.Username, Auth: []ssh.AuthMethod{ssh.Password(t.Password)}, HostKeyCallback: ssh.InsecureIgnoreHostKey(), Timeout: timeout}
}
