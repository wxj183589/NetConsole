package core

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"netconsole-agent/internal/util"
)

const (
	defaultEventLimit = 200
	maxEventLimit     = 1000
)

var ErrInvalidEventCursor = errors.New("事件游标无效")

type Event struct {
	Sequence  int64          `json:"sequence"`
	Timestamp string         `json:"timestamp"`
	Type      string         `json:"type"`
	Source    string         `json:"source"`
	Payload   map[string]any `json:"payload"`
}

type EventPage struct {
	TaskID    string  `json:"task_id"`
	Events    []Event `json:"events"`
	NextAfter int64   `json:"next_after"`
	HasMore   bool    `json:"has_more"`
}

type Artifact struct {
	Name      string `json:"name"`
	Kind      string `json:"kind"`
	Available bool   `json:"available"`
}

type Result struct {
	TaskID       string         `json:"task_id"`
	TaskType     string         `json:"task_type"`
	Status       Status         `json:"status"`
	StartedAt    string         `json:"started_at"`
	FinishedAt   string         `json:"finished_at"`
	Summary      map[string]any `json:"summary"`
	Artifacts    []Artifact     `json:"artifacts"`
	LastSequence int64          `json:"last_sequence"`
	ErrorCode    string         `json:"error_code,omitempty"`
	Error        string         `json:"error"`
}

type resultDocument struct {
	Summary   map[string]any `json:"summary"`
	Artifacts []Artifact     `json:"artifacts"`
}

type eventStore struct {
	path     string
	mu       sync.Mutex
	sequence int64
}

func newEventStore(taskDir string) *eventStore {
	path := filepath.Join(taskDir, "events.jsonl")
	return &eventStore{path: path, sequence: lastSequence(path)}
}

func (s *eventStore) append(eventType, source string, payload map[string]any) (Event, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.sequence++
	event := Event{
		Sequence:  s.sequence,
		Timestamp: time.Now().UTC().Format(time.RFC3339Nano),
		Type:      eventType,
		Source:    source,
		Payload:   payload,
	}
	if event.Payload == nil {
		event.Payload = map[string]any{}
	}
	data, err := json.Marshal(event)
	if err != nil {
		s.sequence--
		return Event{}, err
	}
	file, err := os.OpenFile(s.path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		s.sequence--
		return Event{}, err
	}
	_, writeErr := file.Write(append(data, '\n'))
	closeErr := file.Close()
	if writeErr != nil {
		return Event{}, writeErr
	}
	return event, closeErr
}

func readEventPage(taskID, path string, after int64, limit int) (EventPage, error) {
	if after < 0 {
		return EventPage{}, ErrInvalidEventCursor
	}
	if limit <= 0 {
		limit = defaultEventLimit
	}
	if limit > maxEventLimit {
		limit = maxEventLimit
	}
	page := EventPage{TaskID: taskID, Events: []Event{}, NextAfter: after}
	file, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return page, nil
	}
	if err != nil {
		return EventPage{}, err
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 64*1024), 4*1024*1024)
	for scanner.Scan() {
		var event Event
		if json.Unmarshal(scanner.Bytes(), &event) != nil || event.Sequence <= after {
			continue
		}
		if len(page.Events) >= limit {
			page.HasMore = true
			break
		}
		page.Events = append(page.Events, event)
		page.NextAfter = event.Sequence
	}
	if err := scanner.Err(); err != nil {
		return EventPage{}, err
	}
	return page, nil
}

func lastSequence(path string) int64 {
	file, err := os.Open(path)
	if err != nil {
		return 0
	}
	defer file.Close()
	var last int64
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 64*1024), 4*1024*1024)
	for scanner.Scan() {
		var event Event
		if json.Unmarshal(scanner.Bytes(), &event) == nil && event.Sequence > last {
			last = event.Sequence
		}
	}
	return last
}

func writeResult(taskDir string, summary map[string]any, artifacts []Artifact) error {
	if summary == nil {
		summary = map[string]any{}
	}
	if artifacts == nil {
		artifacts = []Artifact{}
	}
	return util.WriteJSONAtomic(filepath.Join(taskDir, "result.json"), resultDocument{Summary: summary, Artifacts: artifacts}, 0o600)
}

func readResult(task Task, taskDir string) (Result, error) {
	data, err := os.ReadFile(filepath.Join(taskDir, "result.json"))
	if err != nil {
		return Result{}, err
	}
	var document resultDocument
	if err := json.Unmarshal(data, &document); err != nil {
		return Result{}, fmt.Errorf("读取任务结果失败: %w", err)
	}
	for index := range document.Artifacts {
		name := filepath.Base(document.Artifacts[index].Name)
		document.Artifacts[index].Name = name
		document.Artifacts[index].Available = artifactExists(taskDir, name)
	}
	return Result{
		TaskID:       task.TaskID,
		TaskType:     task.TaskType,
		Status:       task.Status,
		StartedAt:    task.StartTime,
		FinishedAt:   task.EndTime,
		Summary:      document.Summary,
		Artifacts:    document.Artifacts,
		LastSequence: lastSequence(filepath.Join(taskDir, "events.jsonl")),
		ErrorCode:    task.ErrorCode,
		Error:        task.ErrorMessage,
	}, nil
}

func artifactExists(taskDir, name string) bool {
	for _, candidate := range []string{filepath.Join(taskDir, name), filepath.Join(taskDir, "raw", name)} {
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			return true
		}
	}
	return false
}
