# Gitbit

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)

A CLI tool for mirroring Git repositories with **full ref fidelity** — all branches, tags, and
notes are preserved. Supports SSH and HTTPS authentication, Git LFS, parallel syncing, and
automatic retries with exponential backoff.

---

## Table of contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Uninstall](#uninstall)
- [Configuration](#configuration)
- [Usage](#usage)
  - [sync — mirror a single repo](#sync--mirror-a-single-repo)
  - [sync-all — mirror all repos from config](#sync-all--mirror-all-repos-from-config)
  - [import-all — fetch only](#import-all--fetch-only)
  - [export-all — push only](#export-all--push-only)
  - [Flags reference](#flags-reference)
  - [Dry-run mode](#dry-run-mode)
  - [Verbose logging](#verbose-logging)
- [Authentication](#authentication)
- [Exit codes](#exit-codes)
- [Contributing](#contributing)
- [License](#license)

---

## Requirements

- Python 3.9 or newer
- `git` installed and available in `$PATH`
- `git-lfs` *(optional — only needed if any repo uses LFS)*

---

## Installation

**macOS / Linux**

```bash
# 1. Clone the repository
git clone https://github.com/siyam-sarker/gitbit.git
cd gitbit

# 2. Create a virtual environment
python3 -m venv .venv

# 3. Activate it
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt
```

**Windows**

```bat
git clone https://github.com/siyam-sarker/gitbit.git
cd gitbit

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
```

**Verify the setup:**

```bash
python -m gitbit --version
# gitbit, version 0.1.0

python -m gitbit --help
```

---

## Uninstall

```bash
# 1. Deactivate the virtual environment (if active)
deactivate

# 2. Delete the project folder
rm -rf /path/to/gitbit          # macOS / Linux
rd /s /q C:\path\to\gitbit      # Windows

# 3. Optionally remove locally stored mirrors
rm -rf ~/.gitbit/mirrors        # macOS / Linux
rd /s /q %USERPROFILE%\.gitbit  # Windows
```

---

## Configuration

Gitbit reads a JSON config file that defines one or more repo mappings.
Copy the bundled example and edit it:

```bash
cp repos.example.json repos.json
```

**Full schema:**

```jsonc
{
  "global": {
    "parallel": 4,                    // number of repos to process concurrently (1–32)
    "timeout": 300,                   // per-repo timeout in seconds
    "verbose": false,                 // enable DEBUG logging
    "mirrors_dir": "~/.gitbit/mirrors" // where local mirror clones are stored
  },
  "repos": [
    {
      "name": "my-repo",              // unique label; local mirror saved as <name>.git
      "source": "git@github.com:org/my-repo.git",
      "dest": "git@backup.example.com:mirrors/my-repo.git",
      "auth": {
        "type": "ssh",
        "private_key": "~/.ssh/id_rsa"  // path to SSH private key; ~ and $VAR expanded
      },
      "lfs": false,                   // set true to also mirror LFS objects
      "submodules": false             // reserved for future use
    },
    {
      "name": "another-repo",
      "source": "https://gitlab.com/team/another-repo.git",
      "dest": "https://git.example.com/team/another-repo.git",
      "auth": {
        "type": "https",
        "token_env": "GITLAB_TOKEN"   // name of the env var that holds the token
      },
      "lfs": false
    }
  ]
}
```

**Auth types:**

| Type | Required field | How it works |
|------|---------------|--------------|
| `ssh` | `private_key` | Sets `GIT_SSH_COMMAND` with the given key |
| `https` | `token_env` | Reads token from the named env var and injects it into the URL |

> Tokens are **never** written to config files or log output.

---

## Usage

All commands are run from the project root with the virtual environment active.

### sync — mirror a single repo

Use this for a quick one-off mirror without a config file.

```bash
python -m gitbit sync --source <SOURCE_URL> --dest <DEST_URL>
```

**Examples:**

```bash
# SSH to SSH
python -m gitbit sync \
  --source git@github.com:org/my-repo.git \
  --dest   git@backup.example.com:mirrors/my-repo.git

# HTTPS to HTTPS (token read from env var)
GITHUB_TOKEN=ghp_xxx \
python -m gitbit sync \
  --source https://github.com/org/my-repo.git \
  --dest   https://git.company.com/org/my-repo.git

# With a custom local mirror name and LFS enabled
python -m gitbit sync \
  --source git@github.com:org/my-repo.git \
  --dest   git@backup.example.com:mirrors/my-repo.git \
  --name   my-repo \
  --lfs

# Custom mirrors directory and timeout
python -m gitbit sync \
  --source git@github.com:org/my-repo.git \
  --dest   git@backup.example.com:mirrors/my-repo.git \
  --mirrors-dir /data/mirrors \
  --timeout 600
```

**All `sync` flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--source` | required | Source Git URL |
| `--dest` | required | Destination Git URL |
| `--name` | `adhoc` | Label for the local mirror directory |
| `--lfs` | off | Also mirror LFS objects |
| `--mirrors-dir` | `~/.gitbit/mirrors` | Where to store the local mirror |
| `--dry-run` | off | Print commands without executing |
| `--timeout` | `300` | Timeout in seconds |
| `--verbose` | off | Enable DEBUG logging |

---

### sync-all — mirror all repos from config

Runs a full import (clone/fetch) then export (push) for every repo in the config file.

```bash
python -m gitbit sync-all -c repos.json
```

**Examples:**

```bash
# Basic sync of all repos
python -m gitbit sync-all -c repos.json

# Run 8 repos in parallel with a 10-minute timeout
python -m gitbit sync-all -c repos.json --parallel 8 --timeout 600

# Preview what would run without executing anything
python -m gitbit sync-all -c repos.json --dry-run

# Show detailed logs
python -m gitbit sync-all -c repos.json --verbose
```

---

### import-all — fetch only

Clones new repos or fetches updates into existing local mirrors. Does **not** push to destinations.
Useful to pull down changes first and push later.

```bash
python -m gitbit import-all -c repos.json
```

**Examples:**

```bash
# Fetch all sources into local mirrors
python -m gitbit import-all -c repos.json

# Dry-run to see what would be cloned/fetched
python -m gitbit import-all -c repos.json --dry-run

# Use 4 parallel workers
python -m gitbit import-all -c repos.json --parallel 4
```

---

### export-all — push only

Pushes all existing local mirrors to their destinations. Does **not** fetch from sources first.
Requires `import-all` to have been run at least once.

```bash
python -m gitbit export-all -c repos.json
```

**Examples:**

```bash
# Push all mirrors to destinations
python -m gitbit export-all -c repos.json

# Dry-run
python -m gitbit export-all -c repos.json --dry-run

# Verbose output
python -m gitbit export-all -c repos.json --verbose
```

---

### Flags reference

**Flags shared by `sync-all`, `import-all`, `export-all`:**

| Flag | Default | Description |
|------|---------|-------------|
| `-c, --config` | required | Path to the JSON config file |
| `--parallel N` | from config | Number of repos to process concurrently |
| `--timeout N` | from config | Per-repo timeout in seconds |
| `--dry-run` | off | Print commands without executing |
| `--verbose` | off | Enable DEBUG logging |

---

### Dry-run mode

Add `--dry-run` to any command to print every git command that *would* run without actually
executing it. Nothing is cloned, fetched, or pushed.

```bash
python -m gitbit sync-all  -c repos.json --dry-run
python -m gitbit import-all -c repos.json --dry-run
python -m gitbit export-all -c repos.json --dry-run

python -m gitbit sync \
  --source git@github.com:org/repo.git \
  --dest   git@backup.example.com:mirrors/repo.git \
  --dry-run
```

---

### Verbose logging

Add `--verbose` to see DEBUG-level output including every git command, retry attempts, and
timing information.

```bash
python -m gitbit sync-all -c repos.json --verbose
```

---

## Authentication

### SSH

Set `"type": "ssh"` and point `"private_key"` to your key file. Gitbit sets `GIT_SSH_COMMAND`
automatically — no `ssh-agent` required.

```jsonc
"auth": {
  "type": "ssh",
  "private_key": "~/.ssh/id_rsa"
}
```

### HTTPS

Set `"type": "https"` and name the environment variable that holds your token.
The token is read at runtime and injected into the URL — it never touches the config file or logs.

```jsonc
"auth": {
  "type": "https",
  "token_env": "GITHUB_TOKEN"
}
```

Then export the token before running:

```bash
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
python -m gitbit sync-all -c repos.json
```

---

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | All repos completed successfully |
| `1` | One or more repos failed, or a config/auth error occurred |

---

## Contributing

### Setup

```bash
git clone https://github.com/siyam-sarker/gitbit.git
cd gitbit
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install pytest pytest-cov pytest-mock flake8 black isort mypy pre-commit
pre-commit install
```

### Running tests

```bash
pytest                          # all tests with coverage
pytest tests/test_config.py -v  # single module
pytest -s --log-cli-level=DEBUG # with debug output
```

### Coding standards

| Tool | Purpose |
|------|---------|
| `black` | Formatter — line length 100 |
| `isort` | Import sorter |
| `flake8` | Linter |
| `mypy --strict` | Type checker |

### Commit style

Follow [Conventional Commits](https://www.conventionalcommits.org/):
`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`

### Reporting security issues

Do not open a public issue. Email `siyam.ts@gmail.com` instead.

---

## License

[MIT](LICENSE) — Copyright (c) 2026 Siyam Sarker
