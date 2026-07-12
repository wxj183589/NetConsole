package target

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"netconsole-agent/internal/util"
)

const MaskedPassword = "******"

type Target struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	Type     string `json:"type"`
	Host     string `json:"host"`
	Protocol string `json:"protocol"`
	Port     int    `json:"port"`
	Username string `json:"username"`
	Password string `json:"password"`
	Remark   string `json:"remark"`
}

type Document struct {
	Targets []Target `json:"targets"`
}

type Store struct {
	mu   sync.RWMutex
	path string
	doc  Document
}

func Open(path string) (*Store, error) {
	s := &Store{path: path}
	if err := s.reload(); err != nil {
		return nil, err
	}
	return s, nil
}

func (s *Store) reload() error {
	b, err := os.ReadFile(s.path)
	if errors.Is(err, os.ErrNotExist) {
		s.doc = Document{Targets: []Target{}}
		return s.saveLocked()
	}
	if err != nil {
		return fmt.Errorf("读取 targets.json 失败: %w", err)
	}
	if err := json.Unmarshal(b, &s.doc); err != nil {
		return fmt.Errorf("解析 targets.json 失败: %w", err)
	}
	return validateDocument(s.doc)
}

func (s *Store) List(mask bool) []Target {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := append([]Target(nil), s.doc.Targets...)
	if mask {
		for i := range out {
			if out[i].Password != "" {
				out[i].Password = MaskedPassword
			}
		}
	}
	return out
}

func (s *Store) Get(id string) (Target, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, t := range s.doc.Targets {
		if t.ID == id {
			return t, true
		}
	}
	return Target{}, false
}

func (s *Store) Create(t Target) (Target, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := validate(t); err != nil {
		return Target{}, err
	}
	for _, current := range s.doc.Targets {
		if current.ID == t.ID {
			return Target{}, fmt.Errorf("目标 ID 已存在: %s", t.ID)
		}
	}
	s.doc.Targets = append(s.doc.Targets, t)
	return t, s.saveLocked()
}

func (s *Store) Update(id string, t Target) (Target, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i, current := range s.doc.Targets {
		if current.ID != id {
			continue
		}
		t.ID = id
		if t.Password == MaskedPassword {
			t.Password = current.Password
		}
		if err := validate(t); err != nil {
			return Target{}, err
		}
		s.doc.Targets[i] = t
		return t, s.saveLocked()
	}
	return Target{}, fmt.Errorf("目标不存在: %s", id)
}

func (s *Store) Delete(id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i, current := range s.doc.Targets {
		if current.ID == id {
			s.doc.Targets = append(s.doc.Targets[:i], s.doc.Targets[i+1:]...)
			return s.saveLocked()
		}
	}
	return fmt.Errorf("目标不存在: %s", id)
}

func (s *Store) Import(doc Document) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i := range doc.Targets {
		if doc.Targets[i].Password != MaskedPassword {
			continue
		}
		doc.Targets[i].Password = ""
		for _, current := range s.doc.Targets {
			if current.ID == doc.Targets[i].ID {
				doc.Targets[i].Password = current.Password
				break
			}
		}
	}
	if err := validateDocument(doc); err != nil {
		return err
	}
	s.doc = doc
	return s.saveLocked()
}

func (s *Store) saveLocked() error {
	if err := os.MkdirAll(filepath.Dir(s.path), 0o755); err != nil {
		return err
	}
	b, err := json.MarshalIndent(s.doc, "", "  ")
	if err != nil {
		return err
	}
	tmp := s.path + ".tmp"
	if err := os.WriteFile(tmp, append(b, '\n'), 0o600); err != nil {
		return err
	}
	if err := util.ReplaceFile(tmp, s.path); err != nil {
		_ = os.Remove(tmp)
		return err
	}
	return nil
}

func validateDocument(doc Document) error {
	seen := map[string]bool{}
	for _, t := range doc.Targets {
		if err := validate(t); err != nil {
			return err
		}
		if seen[t.ID] {
			return fmt.Errorf("目标 ID 重复: %s", t.ID)
		}
		seen[t.ID] = true
	}
	return nil
}

func validate(t Target) error {
	if strings.TrimSpace(t.ID) == "" || strings.TrimSpace(t.Name) == "" || strings.TrimSpace(t.Host) == "" {
		return errors.New("目标 id、name、host 不能为空")
	}
	if strings.ContainsAny(t.ID, `/\\`) || t.ID == "." || t.ID == ".." {
		return errors.New("目标 id 不得包含路径分隔符")
	}
	switch strings.ToLower(t.Protocol) {
	case "ssh", "telnet", "local":
	default:
		return fmt.Errorf("不支持的目标协议: %s", t.Protocol)
	}
	if !strings.EqualFold(t.Protocol, "local") && (t.Port <= 0 || t.Port > 65535) {
		return errors.New("远程目标端口必须在 1-65535")
	}
	return nil
}

func Sanitized(t Target) Target {
	if t.Password != "" {
		t.Password = MaskedPassword
	}
	return t
}
