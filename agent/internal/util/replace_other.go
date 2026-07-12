//go:build !windows

package util

import "os"

func ReplaceFile(source, destination string) error { return os.Rename(source, destination) }
