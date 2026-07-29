//go:build windows

package main

import (
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

const (
	maxRequestBytes              = 256 * 1024
	seeMaskNoCloseProcess        = 0x00000040
	seeMaskFlagNoUI              = 0x00000400
	swShowNormal                 = 1
	errorCancelled               = 1223
	elevationCancelledExitCode   = 23
	elevatedLaunchFailedExitCode = 24
)

type launchRequest struct {
	Version          int      `json:"version"`
	ExecutablePath   string   `json:"executable_path"`
	Arguments        []string `json:"arguments"`
	WorkingDirectory string   `json:"working_directory"`
}

type shellExecuteInfo struct {
	Size       uint32
	Mask       uint32
	Window     uintptr
	Verb       *uint16
	File       *uint16
	Parameters *uint16
	Directory  *uint16
	Show       int32
	Instance   uintptr
	IDList     uintptr
	Class      *uint16
	ClassKey   uintptr
	HotKey     uint32
	Icon       uintptr
	Process    uintptr
}

var (
	shell32         = syscall.NewLazyDLL("shell32.dll")
	kernel32        = syscall.NewLazyDLL("kernel32.dll")
	shellExecuteExW = shell32.NewProc("ShellExecuteExW")
	closeHandle     = kernel32.NewProc("CloseHandle")
)

func main() {
	if len(os.Args) != 1 {
		os.Exit(2)
	}
	request, err := decodeRequest(io.LimitReader(os.Stdin, maxRequestBytes+1))
	if err != nil || validateRequest(request) != nil {
		os.Exit(2)
	}
	code := executeElevated(request)
	os.Exit(code)
}

func decodeRequest(reader io.Reader) (launchRequest, error) {
	var request launchRequest
	decoder := json.NewDecoder(reader)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&request); err != nil {
		return request, err
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return request, errors.New("request has trailing data")
	}
	return request, nil
}

func validateRequest(request launchRequest) error {
	if request.Version != 1 || len(request.Arguments) > 64 {
		return errors.New("invalid request")
	}
	if err := validateAbsolutePath(request.ExecutablePath, ".exe", false); err != nil {
		return err
	}
	if err := validateAbsolutePath(request.WorkingDirectory, "", true); err != nil {
		return err
	}
	for _, argument := range request.Arguments {
		if len(argument) > 2000 || hasControl(argument) || hasShellToken(argument) {
			return errors.New("invalid argument")
		}
	}
	return nil
}

func validateAbsolutePath(value string, extension string, directory bool) error {
	if value == "" || !filepath.IsAbs(value) || hasControl(value) {
		return errors.New("invalid path")
	}
	if extension != "" && !strings.EqualFold(filepath.Ext(value), extension) {
		return errors.New("invalid extension")
	}
	info, err := os.Lstat(value)
	if err != nil || info.Mode()&os.ModeSymlink != 0 {
		return errors.New("path unavailable")
	}
	if directory != info.IsDir() {
		return errors.New("path type mismatch")
	}
	return nil
}

func executeElevated(request launchRequest) int {
	verb, _ := syscall.UTF16PtrFromString("runas")
	file, _ := syscall.UTF16PtrFromString(request.ExecutablePath)
	parameters, _ := syscall.UTF16PtrFromString(joinWindowsArguments(request.Arguments))
	directory, _ := syscall.UTF16PtrFromString(request.WorkingDirectory)
	info := shellExecuteInfo{
		Size:       uint32(unsafe.Sizeof(shellExecuteInfo{})),
		Mask:       seeMaskNoCloseProcess | seeMaskFlagNoUI,
		Verb:       verb,
		File:       file,
		Parameters: parameters,
		Directory:  directory,
		Show:       swShowNormal,
	}
	result, _, callError := shellExecuteExW.Call(uintptr(unsafe.Pointer(&info)))
	if result == 0 {
		if errno, ok := callError.(syscall.Errno); ok && errno == errorCancelled {
			return elevationCancelledExitCode
		}
		return elevatedLaunchFailedExitCode
	}
	if info.Process != 0 {
		closeHandle.Call(info.Process)
	}
	return 0
}

func joinWindowsArguments(arguments []string) string {
	quoted := make([]string, 0, len(arguments))
	for _, argument := range arguments {
		quoted = append(quoted, quoteWindowsArgument(argument))
	}
	return strings.Join(quoted, " ")
}

func quoteWindowsArgument(argument string) string {
	var builder strings.Builder
	builder.WriteByte('"')
	backslashes := 0
	for _, character := range argument {
		if character == '\\' {
			backslashes++
			continue
		}
		if character == '"' {
			builder.WriteString(strings.Repeat("\\", backslashes*2+1))
			builder.WriteRune(character)
			backslashes = 0
			continue
		}
		builder.WriteString(strings.Repeat("\\", backslashes))
		backslashes = 0
		builder.WriteRune(character)
	}
	builder.WriteString(strings.Repeat("\\", backslashes*2))
	builder.WriteByte('"')
	return builder.String()
}

func hasControl(value string) bool {
	return strings.ContainsAny(value, "\x00\r\n")
}

func hasShellToken(value string) bool {
	return strings.Contains(value, "&&") ||
		strings.Contains(value, "||") ||
		strings.ContainsAny(value, "|<>")
}
