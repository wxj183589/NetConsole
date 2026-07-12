//go:build windows

package tray

import (
	"github.com/getlantern/systray"
	"log"
	"os"
	"os/exec"
	"path/filepath"
)

type Options struct {
	URL, DataDir, LogDir, PackageDir string
	Stop                             func()
}

func Run(options Options) {
	systray.Run(func() {
		systray.SetTitle("NetConsole Agent")
		systray.SetTooltip("NetConsole Agent")
		title := systray.AddMenuItem("NetConsole Agent", "")
		title.Disable()
		openWeb := systray.AddMenuItem("打开 Web 页面", "")
		openData := systray.AddMenuItem("打开数据目录", "")
		openLogs := systray.AddMenuItem("打开日志目录", "")
		openPackages := systray.AddMenuItem("打开采集包目录", "")
		quit := systray.AddMenuItem("退出", "")
		go func() {
			for {
				select {
				case <-openWeb.ClickedCh:
					_ = OpenURL(options.URL)
				case <-openData.ClickedCh:
					openDir(options.DataDir)
				case <-openLogs.ClickedCh:
					openDir(options.LogDir)
				case <-openPackages.ClickedCh:
					openDir(options.PackageDir)
				case <-quit.ClickedCh:
					if options.Stop != nil {
						options.Stop()
					}
					systray.Quit()
					return
				}
			}
		}()
	}, func() {})
}
func Quit() { systray.Quit() }
func OpenURL(url string) error {
	return exec.Command("rundll32.exe", "url.dll,FileProtocolHandler", url).Start()
}
func openDir(dir string) {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		log.Printf("创建目录失败 %s: %v", dir, err)
		return
	}
	_ = exec.Command("explorer.exe", filepath.Clean(dir)).Start()
}
