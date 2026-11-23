"""Readable transcript projection. Raw ordered events remain the authority."""

from __future__ import annotations

import re
from collections import deque

PROMPT = re.compile(
    r"^(?P<prompt><[^<>\r\n]{1,160}>|\[[^\[\]\r\n]{1,160}\]|[\w.@:/~-]+[#$>])\s*(?P<command>.*)$"
)
PAGER = re.compile(r"^\s*-{2,}\s*More\s*-{2,}\s*$", re.I)


class InputEditor:
    def __init__(self):
        self.line = ""
        self.cursor = 0
        self.escape = ""
        self.uncertain = False
        self.last_cr = False

    def feed(self, data):
        commands = []
        for char in data:
            if self.escape:
                self.escape += char
                if len(self.escape) == 2 and char in "[O":
                    continue
                if len(self.escape) >= 3 and "@" <= char <= "~":
                    code = self.escape[2:]
                    if code == "D":
                        self.cursor = max(0, self.cursor - 1)
                    elif code == "C":
                        self.cursor = min(len(self.line), self.cursor + 1)
                    elif code in {"H", "1~"}:
                        self.cursor = 0
                    elif code in {"F", "4~"}:
                        self.cursor = len(self.line)
                    elif code == "3~":
                        self.line = (
                            self.line[: self.cursor] + self.line[self.cursor + 1 :]
                        )
                    else:
                        self.uncertain = True
                    self.escape = ""
                elif len(self.escape) > 32:
                    self.escape = ""
                    self.uncertain = True
                continue
            if char == "\x1b":
                self.escape = char
            elif char == "\n" and self.last_cr:
                self.last_cr = False
            elif char in "\r\n":
                commands.append((self.line, not self.uncertain))
                self.line, self.cursor, self.uncertain = "", 0, False
                self.last_cr = char == "\r"
            elif char in "\x08\x7f":
                if self.cursor:
                    self.line = self.line[: self.cursor - 1] + self.line[self.cursor :]
                    self.cursor -= 1
            elif char == "\x15":
                self.line, self.cursor = self.line[self.cursor :], 0
            elif char == "\x17":
                prefix = re.sub(r"\S+\s*$", "", self.line[: self.cursor])
                self.line, self.cursor = prefix + self.line[self.cursor :], len(prefix)
            elif char in "\x03\x04":
                self.line, self.cursor, self.uncertain = "", 0, False
            elif char == "\t":
                self.uncertain = True
            elif char >= " ":
                self.last_cr = False
                self.line = self.line[: self.cursor] + char + self.line[self.cursor :]
                self.cursor += 1
        return commands


class Transcript:
    def __init__(self, stream):
        self.stream = stream
        self.editor = InputEditor()
        self.pending = deque()
        self.line = []
        self.cursor = 0
        self.escape = ""
        self.prompt = ""
        self.blank = False
        self.last_prompt = ""
        self.pagers = 0
        self.uncertain_commands = 0
        self.draft_echo = ""
        self.pager_active = False

    def event(self, event):
        kind, data = event.get("event_type"), str(event.get("data") or "")
        if kind in {"INPUT", "COMMAND_INPUT"}:
            # A pager's continuation is an interaction control, not a command.
            if self.pager_active or PAGER.search("".join(self.line)):
                self.pagers += 1
                return
            for command, reliable in self.editor.feed(data):
                text = "".join(self.line).rstrip()
                match = PROMPT.match(text)
                if match:
                    self.prompt = match["prompt"]
                    if not match["command"]:
                        self.line, self.cursor = [], 0
                if command.strip() or not reliable:
                    self.pending.append((command, reliable))
                if self.draft_echo and (command.strip() or not reliable):
                    if not reliable:
                        self.pending[-1] = (self.draft_echo, True)
                    self.draft_echo = ""
        elif kind in {"OUTPUT", "TERMINAL_OUTPUT"}:
            self.output(data)

    def output(self, data):
        for char in data:
            if self.escape:
                self.escape += char
                if self.escape.startswith("\x1b]"):
                    if char == "\x07" or self.escape.endswith("\x1b\\"):
                        self.escape = ""
                elif len(self.escape) >= 3 and "@" <= char <= "~":
                    seq = self.escape[2:]
                    amount = (
                        int(seq[:-1] or "1")
                        if seq[:-1].isdigit() or not seq[:-1]
                        else 1
                    )
                    if char == "K":
                        if seq == "2K":
                            self.line = []
                        elif seq == "1K":
                            self.line[: self.cursor] = [" "] * min(
                                self.cursor, len(self.line)
                            )
                        else:
                            self.line = self.line[: self.cursor]
                    elif char == "D":
                        self.cursor = max(0, self.cursor - amount)
                    elif char == "C":
                        self.cursor = min(65536, self.cursor + amount)
                    elif char == "G":
                        self.cursor = max(0, amount - 1)
                    self.escape = ""
                elif len(self.escape) > 4096:
                    self.escape = ""
                continue
            if char == "\x1b":
                self.escape = char
            elif char == "\r":
                self.cursor = 0
            elif char == "\n":
                self.flush_line()
            elif char in "\b\x7f":
                self.cursor = max(0, self.cursor - 1)
            elif char == "\t":
                self._put(" " * (8 - self.cursor % 8))
            elif char >= " ":
                self._put(char)
                if len(self.line) <= 128 and PAGER.search("".join(self.line)):
                    self.pager_active = True
            if self.cursor > 65536:
                self.flush_line()

    def _put(self, text):
        for char in text:
            if self.cursor >= len(self.line):
                self.line.extend([" "] * (self.cursor - len(self.line) + 1))
            self.line[self.cursor] = char
            self.cursor += 1

    def _write(self, text):
        if not text.strip():
            if not self.blank:
                self.stream.write("\n")
            self.blank = True
            return
        self.blank = False
        self.stream.write(text.rstrip() + "\n")

    def flush_line(self):
        text = "".join(self.line).rstrip()
        self.line, self.cursor = [], 0
        if PAGER.search(text):
            self.pagers += 1
            text = PAGER.sub("", text).rstrip()
            if not text:
                return
        self.pager_active = False
        match = PROMPT.match(text)
        if match:
            self.prompt = match["prompt"]
            if (
                match["command"]
                and not self.pending
                and (self.editor.line or self.editor.uncertain)
            ):
                # Redraws from Tab/history before Enter are edit states, not executions.
                self.draft_echo = match["command"]
                return
        if self.pending:
            command, reliable = self.pending[0]
            echo = match["command"] if match else text.strip()
            if echo and (
                (not reliable and match is not None)
                or (reliable and echo.strip() == command.strip())
            ):
                self.pending.popleft()
                self._write(f"{self.prompt} {echo}".lstrip())
                self.last_prompt = ""
                return
            if match and not match["command"]:
                self.pending.popleft()
                if reliable:
                    self._write(f"{self.prompt} {command}")
                else:
                    self.uncertain_commands += 1
                    self._write("[命令无法可靠还原：历史/补全未返回完整回显]")
            elif not match:
                self.pending.popleft()
                if reliable:
                    self._write(f"{self.prompt} {command}".lstrip())
                else:
                    self.uncertain_commands += 1
                    self._write("[命令无法可靠还原：历史/补全未返回完整回显]")
        if match and not match["command"]:
            # Coalesce only adjacent empty prompts, never executed commands/output.
            if text == self.last_prompt:
                return
            self.last_prompt = text
        elif text.strip():
            self.last_prompt = ""
        self._write(text)

    def finish(self):
        if self.line:
            self.flush_line()
        while self.pending:
            command, reliable = self.pending.popleft()
            if reliable:
                self._write(f"{self.prompt} {command}".lstrip())
            else:
                self.uncertain_commands += 1
                self._write("[命令无法可靠还原：历史/补全未返回完整回显]")


def render_events(events, destination):
    transcript = Transcript(destination)
    for event in events:
        transcript.event(event)
    transcript.finish()
    return {
        "uncertain_commands": transcript.uncertain_commands,
        "pagers_removed": transcript.pagers,
    }
