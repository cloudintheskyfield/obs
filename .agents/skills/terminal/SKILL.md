---
name: terminal
description: Execute bash commands and scripts in the workspace directory
---

# Terminal Skill

Run commands in a bash shell to perform system operations, run scripts, install packages, and interact with the filesystem.

## Quick Start

Run a simple command:

```python
result = await execute_skill("bash", command="ls -la")
```

Run command with timeout:

```python
result = await execute_skill("bash", command="python train.py", timeout=300)
```

Run with fresh shell:

```python
result = await execute_skill("bash", command="git status", restart=True)
```

## Parameters

- **command** (required): The bash command to execute
- **timeout** (optional): Execution timeout in seconds (default: 30)
- **restart** (optional): Start fresh shell session (default: false)

## Allowed Commands

### File Operations
`ls`, `dir`, `pwd`, `cd`, `cat`, `head`, `tail`, `find`, `grep`, `sort`, `uniq`, `wc`, `du`, `df`, `which`, `cp`, `mv`, `rm`, `mkdir`, `rmdir`, `touch`, `chmod`, `chown`

### Development Tools
- **Python**: `python`, `python3`, `pip`, `pip3`, `uv`
- **Node.js**: `node`, `npm`, `yarn`, `pnpm`
- **Rust**: `cargo`, `rustc`
- **Go**: `go`
- **Java**: `java`, `javac`
- **C/C++**: `gcc`, `g++`, `make`, `cmake`

### Version Control
`git` (all subcommands: clone, pull, push, commit, status, etc.)

### System Utilities
`ps`, `kill`, `top`, `htop`, `free`, `uptime`, `curl`, `wget`, `ping`, `netstat`, `ss`

### Archive Tools
`zip`, `unzip`, `tar`, `gzip`, `gunzip`

### Text Processing
`awk`, `sed`, `cut`, `tr`, `echo`

### Package Managers
`apt`, `yum`, `dnf`, `pacman`, `brew`

## Workflows

### Python Project Setup
```bash
# Create virtual environment
python -m venv venv

# Activate and install dependencies
source venv/bin/activate && pip install -r requirements.txt

# Run tests
pytest tests/
```

### Git Workflow
```bash
# Check status
git status

# Stage changes
git add .

# Commit
git commit -m "Update feature"

# Push
git push origin main
```

### Build and Deploy
```bash
# Install dependencies
npm install

# Build project
npm run build

# Run tests
npm test
```

## Safety Features

### Blocked Commands
These dangerous commands are automatically blocked:
- `rm -rf /` (and variants)
- `dd if=/dev/random` (disk operations)
- `mkfs`, `fdisk`, `parted` (partition tools)
- `shutdown`, `reboot`, `halt`, `poweroff`
- `killall -9`, `pkill -9` (mass kill)
- `chmod -R 777 /`, `chown -R root:root /`
- Fork bombs and malicious scripts

### Security Checks
- Commands are validated before execution
- Execution happens in workspace directory only
- Timeout protection prevents infinite loops
- Output is captured and logged
- Dangerous patterns are detected and blocked

## Best Practices

- **Use timeouts**: Set appropriate timeout for long-running commands
- **Check output**: Always verify command output for errors
- **Restart shell when needed**: Use `restart=True` for clean environment
- **Combine commands carefully**: Use `&&` for dependent commands, `||` for fallbacks
- **Redirect output**: Capture logs with `> output.log 2>&1`
- **Test before automation**: Run commands manually first to verify

## Error Handling

- **Command not found**: Install required tool or check command name
- **Permission denied**: Check file/directory permissions
- **Timeout**: Increase timeout parameter or optimize command
- **Exit code != 0**: Command failed, check error output
- **Blocked command**: Use safer alternative or break into smaller steps

## Advanced Usage

### Pipes and Redirects
```bash
cat file.txt | grep "pattern" | sort | uniq > results.txt
```

### Environment Variables
```bash
export VAR=value && python script.py
```

### Background Processes
```bash
nohup python server.py > server.log 2>&1 &
```

### Conditional Execution
```bash
mkdir build && cd build && cmake .. && make
```

## Examples

See `examples/` directory for:
- CI/CD pipeline scripts
- Database migration commands
- Multi-language project builds
- System administration tasks
