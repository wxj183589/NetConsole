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
	"syscall"
	"time"

	"netconsole-agent/internal/api"
	"netconsole-agent/internal/config"
	"netconsole-agent/internal/core"
	"netconsole-agent/internal/packagex"
	"netconsole-agent/internal/target"
)

var version = "v1.0.0-windows"

func main() {
	configPath := flag.String("config", "config.json", "配置文件路径")
	targetsPath := flag.String("targets", "targets.json", "目标设备文件路径")
	flag.Parse()
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
	server := &http.Server{Addr: cfg.ListenAddress(), Handler: api.New(cfg, targetStore, taskManager, packager, version).Handler(), ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 120 * time.Second}
	fmt.Printf("NetConsole Agent %s 正在监听 http://%s\n", version, cfg.ListenAddress())
	log.Printf("Agent 启动 listen=%s", cfg.ListenAddress())
	errCh := make(chan error, 1)
	go func() { errCh <- server.ListenAndServe() }()
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(signals)
	select {
	case sig := <-signals:
		log.Printf("收到退出信号 %s，正在停止任务", sig)
	case err := <-errCh:
		if err != nil && err != http.ErrServerClosed {
			log.Printf("HTTP 服务异常退出: %v", err)
		}
	}
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = server.Shutdown(shutdownCtx)
	stopped := taskManager.StopAll()
	if len(stopped) > 0 {
		log.Printf("已请求停止 %d 个运行任务", len(stopped))
	}
	if !taskManager.WaitAll(20 * time.Second) {
		log.Printf("等待任务停止超时，Agent 即将退出")
	}
}
