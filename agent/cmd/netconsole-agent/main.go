package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
	"syscall"
	"time"

	"netconsole-agent/internal/api"
	"netconsole-agent/internal/config"
	"netconsole-agent/internal/core"
	"netconsole-agent/internal/packagex"
	"netconsole-agent/internal/power"
	"netconsole-agent/internal/target"
	"netconsole-agent/internal/tray"
)

var version = "v1.0.0-windows"

func main() {
	configPath := flag.String("config", "config.json", "配置文件路径")
	targetsPath := flag.String("targets", "targets.json", "目标设备文件路径")
	consoleMode := flag.Bool("console", false, "控制台调试模式")
	openWeb := flag.Bool("open", false, "启动后打开 Web 页面")
	showVersion := flag.Bool("version", false, "显示版本")
	flag.Parse()
	if *showVersion {
		fmt.Println(version)
		return
	}
	cfg, err := config.Load(*configPath)
	if err != nil {
		log.Fatal(err)
	}
	resolvedTargets := *targetsPath
	if !filepath.IsAbs(resolvedTargets) {
		resolvedTargets = filepath.Join(cfg.BaseDir, resolvedTargets)
	}
	targetStore, err := target.Open(resolvedTargets)
	if err != nil {
		log.Fatal(err)
	}
	packager := &packagex.Packager{Dir: cfg.PackagePath(), AgentID: cfg.Agent.ID, AgentName: cfg.Agent.Name, Version: version}
	taskManager, err := core.NewManager(cfg.DataPath(), packager, cfg.Runtime.AutoPackageOnStop)
	if err != nil {
		log.Fatal(err)
	}
	logFile, err := os.OpenFile(filepath.Join(cfg.LogPath(), "agent.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		log.Fatal(err)
	}
	defer logFile.Close()
	log.SetOutput(logFile)
	log.SetFlags(log.Ldate | log.Ltime | log.Lmicroseconds)
	powerManager := power.New()
	if cfg.Power.PreventSleepOnStart {
		if err := powerManager.PreventSleep("agent_started"); err != nil {
			log.Printf("启用防休眠失败: %v", err)
		}
	}
	server := &http.Server{Addr: cfg.ListenAddress(), Handler: api.New(cfg, targetStore, taskManager, packager, version, powerManager).Handler(), ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 120 * time.Second}
	go func() {
		ticker := time.NewTicker(500 * time.Millisecond)
		defer ticker.Stop()
		for range ticker.C {
			current, _ := taskManager.Counts()
			powerManager.SetTaskRunning(current > 0, cfg.Power.KeepDisplayOnWhenTaskRunning)
		}
	}()
	webURL := browserURL(cfg)
	fmt.Printf("NetConsole Agent %s 正在监听 %s\n", version, webURL)
	log.Printf("Agent 启动 listen=%s", cfg.ListenAddress())
	errCh := make(chan error, 1)
	go func() { errCh <- server.ListenAndServe() }()
	if *openWeb {
		_ = tray.OpenURL(webURL)
	}
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(signals)
	stopAgent := func() {
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		_ = server.Shutdown(shutdownCtx)
		cancel()
		stopped := taskManager.StopAll()
		if len(stopped) > 0 {
			log.Printf("已请求停止 %d 个运行任务", len(stopped))
		}
		if !taskManager.WaitAll(20 * time.Second) {
			log.Printf("等待任务停止超时，Agent 即将退出")
		}
		if cfg.Power.RestoreOnExit {
			if err := powerManager.Restore("agent_exit"); err != nil {
				log.Printf("恢复系统电源失败: %v", err)
			}
		}
	}
	if runtime.GOOS == "windows" && !*consoleMode {
		tray.Run(tray.Options{URL: webURL, DataDir: cfg.DataPath(), LogDir: cfg.LogPath(), PackageDir: cfg.PackagePath(), Stop: stopAgent})
		return
	}
	select {
	case sig := <-signals:
		log.Printf("收到退出信号 %s，正在停止任务", sig)
	case err := <-errCh:
		if err != nil && err != http.ErrServerClosed {
			log.Printf("HTTP 服务异常退出: %v", err)
		}
	}
	stopAgent()
}

func browserURL(cfg *config.Config) string {
	host := cfg.Agent.ListenHost
	if host == "" || host == "0.0.0.0" || host == "::" {
		host = "127.0.0.1"
	}
	return fmt.Sprintf("http://%s:%d", host, cfg.Agent.ListenPort)
}
