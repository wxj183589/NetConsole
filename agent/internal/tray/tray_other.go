//go:build !windows

package tray

type Options struct {
	URL, DataDir, LogDir, PackageDir string
	Stop                             func()
}

func Run(options Options) {
	if options.Stop != nil {
		options.Stop()
	}
}
func Quit()                {}
func OpenURL(string) error { return nil }
