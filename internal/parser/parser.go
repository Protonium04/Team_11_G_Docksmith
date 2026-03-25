package parser

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

var validInstructions = map[string]bool{
	"FROM": true, "COPY": true, "RUN": true,
	"WORKDIR": true, "ENV": true, "CMD": true,
}

// Instruction represents one parsed line from a Docksmithfile.
type Instruction struct {
	Type       string
	Args       string
	LineNumber int
}

// ParseDocksmithfile reads a Docksmithfile and returns all instructions.
func ParseDocksmithfile(filePath string) ([]Instruction, error) {
	f, err := os.Open(filePath)
	if err != nil {
		return nil, fmt.Errorf("[BUILD ERROR] Docksmithfile not found at: %s", filePath)
	}
	defer f.Close()

	var instructions []Instruction
	scanner := bufio.NewScanner(f)
	lineNum := 0

	for scanner.Scan() {
		lineNum++
		line := strings.TrimSpace(scanner.Text())

		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		parts := strings.SplitN(line, " ", 2)
		keyword := strings.ToUpper(parts[0])
		args := ""
		if len(parts) > 1 {
			args = strings.TrimSpace(parts[1])
		}

		if !validInstructions[keyword] {
			return nil, fmt.Errorf("[PARSE ERROR] Line %d: Unknown instruction %q.\n  Valid instructions: CMD, COPY, ENV, FROM, RUN, WORKDIR\n  Got: %q",
				lineNum, parts[0], line)
		}

		if err := validateArgs(keyword, args, lineNum); err != nil {
			return nil, err
		}

		instructions = append(instructions, Instruction{
			Type:       keyword,
			Args:       args,
			LineNumber: lineNum,
		})
	}

	if len(instructions) == 0 {
		return nil, fmt.Errorf("[PARSE ERROR] Docksmithfile is empty or has no valid instructions")
	}
	if instructions[0].Type != "FROM" {
		return nil, fmt.Errorf("[PARSE ERROR] Line %d: Docksmithfile must start with FROM, got %q",
			instructions[0].LineNumber, instructions[0].Type)
	}

	return instructions, nil
}

func validateArgs(keyword, args string, lineNum int) error {
	switch keyword {
	case "FROM":
		if args == "" {
			return fmt.Errorf("[PARSE ERROR] Line %d: FROM needs an image name.\n  Example: FROM alpine:latest", lineNum)
		}
	case "COPY":
		if len(strings.Fields(args)) < 2 {
			return fmt.Errorf("[PARSE ERROR] Line %d: COPY needs <src> and <dest>.\n  Example: COPY . /app", lineNum)
		}
	case "RUN":
		if args == "" {
			return fmt.Errorf("[PARSE ERROR] Line %d: RUN needs a command.\n  Example: RUN echo hello", lineNum)
		}
	case "WORKDIR":
		if args == "" {
			return fmt.Errorf("[PARSE ERROR] Line %d: WORKDIR needs a path.\n  Example: WORKDIR /app", lineNum)
		}
	case "ENV":
		if !strings.Contains(args, "=") {
			return fmt.Errorf("[PARSE ERROR] Line %d: ENV must be KEY=value.\n  Example: ENV APP_NAME=myapp\n  Got: %q", lineNum, args)
		}
	case "CMD":
		var result []interface{}
		if err := json.Unmarshal([]byte(args), &result); err != nil {
			return fmt.Errorf("[PARSE ERROR] Line %d: CMD must be a JSON string array.\n  Example: CMD [\"python\", \"main.py\"]\n  Got: %q", lineNum, args)
		}
		for _, v := range result {
			if _, ok := v.(string); !ok {
				return fmt.Errorf("[PARSE ERROR] Line %d: CMD array must contain only strings", lineNum)
			}
		}
	}
	return nil
}

// ParseFromArgs parses "alpine:latest" → ("alpine", "latest").
func ParseFromArgs(args string) (name, tag string) {
	if idx := strings.Index(args, ":"); idx >= 0 {
		return strings.TrimSpace(args[:idx]), strings.TrimSpace(args[idx+1:])
	}
	return strings.TrimSpace(args), "latest"
}

// ParseEnvArgs parses "KEY=value" → ("KEY", "value").
func ParseEnvArgs(args string) (key, value string, err error) {
	idx := strings.Index(args, "=")
	if idx < 0 {
		return "", "", fmt.Errorf("[PARSE ERROR] ENV must be KEY=value. Got: %q", args)
	}
	return strings.TrimSpace(args[:idx]), strings.TrimSpace(args[idx+1:]), nil
}

// ParseCopyArgs parses ". /app" → (".", "/app").
func ParseCopyArgs(args string) (src, dest string, err error) {
	parts := strings.Fields(args)
	if len(parts) < 2 {
		return "", "", fmt.Errorf("[PARSE ERROR] COPY needs <src> and <dest>. Got: %q", args)
	}
	return parts[0], parts[1], nil
}

// ParseCmdArgs parses a JSON array string into []string.
func ParseCmdArgs(args string) ([]string, error) {
	var result []string
	if err := json.Unmarshal([]byte(args), &result); err != nil {
		return nil, fmt.Errorf("[PARSE ERROR] CMD must be a JSON array. Got: %q", args)
	}
	return result, nil
}
