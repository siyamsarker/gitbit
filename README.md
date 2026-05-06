# Gitbit

[![PyPI](https://img.shields.io/pypi/v/gitbit)](https://pypi.org/project/gitbit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/gitbit)](https://pypi.org/project/gitbit/)

A production-ready CLI tool for mirroring Git repositories with **full ref fidelity** — all
branches, tags, and notes are preserved. Supports SSH and HTTPS authentication, Git LFS, concurrent
syncing, and automatic retries.

---

## Features

- **Full mirror fidelity** — uses `git clone --mirror` / `git push --mirror` under the hood.
- **SSH and HTTPS auth** — SSH via `GIT_SSH_COMMAND`; HTTPS via token from an environment variable (no plaintext secrets in config).
- **Git LFS** — optional `git lfs fetch/push --all` for repos with large files.
- **Concurrent** — configurable `ThreadPoolExecutor` for parallel multi-repo operations.
- **Retries** — exponential backoff + jitter via `tenacity` (up to 5 attempts per repo).
- **Dry-run mode** — `--dry-run` prints every command without executing it.
- **Disk-space guard** — refuses to clone if less than 1 GB is available.
- **Structured logging** — ISO 8601 timestamps, level-aligned, stderr only.
- **Credentials never logged** — `safe_url()` strips tokens before any log output.

---

## Installation

### pip

```bash
pip install gitbit
```

Requires Python ≥ 3.9, `git` in `$PATH`, and (optionally) `git-lfs`.

### From source

```bash
git clone https://github.com/your-org/gitbit.git
cd gitbit
pip install -e ".[dev]"
```

---

## Quick start

### Ad-hoc single repo (no config file)

```bash
gitbit sync \
  --source git@github.com:org/my-repo.git \
  --dest   git@backup.example.com:mirrors/my-repo.git \
  --name   my-repo
```

### Config-file driven (multiple repos)

1. Copy the example config and edit it:

```bash
cp repos.example.json repos.json
$EDITOR repos.json
```

2. Export any required tokens:

```bash
export GITLAB_TOKEN=glpat-xxxxxxxxxxxx
```

3. Run:

```bash
# Import + export in one step
gitbit sync-all -c repos.json

# Or split the two phases
gitbit import-all -c repos.json
gitbit export-all -c repos.json
```

---

## Configuration schema

`repos.json` is a JSON file validated by Pydantic. All fields under `global` are optional.

```jsonc
{
  "global": {
    "parallel": 4,          // max concurrent repos (1–32, default 4)
    "timeout": 300,         // per-repo timeout in seconds (default 300)
    "verbose": false,       // enable DEBUG logging (default false)
    "mirrors_dir": "~/.gitbit/mirrors"  // local mirror storage root
  },
  "repos": [
    {
      "name": "ProjectA",                            // unique name; becomes <name>.git on disk
      "source": "git@github.com:org/ProjectA.git",  // source URL
      "dest":   "git@backup.example.com:mirrors/ProjectA.git",  // destination URL
      "auth": {
        "type": "ssh",
        "private_key": "~/.ssh/id_rsa"   // ~ and $VARS are expanded
      },
      "lfs": true,          // mirror LFS objects (default false)
      "submodules": false   // reserved for future use
    },
    {
      "name": "RepoB",
      "source": "https://gitlab.com/team/RepoB.git",
      "dest":   "https://git.example.com/team/RepoB.git",
      "auth": {
        "type": "https",
        "token_env": "GITLAB_TOKEN"   // env var name (never the token itself)
      },
      "lfs": false
    }
  ]
}
```

---

## CLI reference

```
Usage: gitbit [OPTIONS] COMMAND [ARGS]...

  Gitbit — mirror Git repositories with full ref fidelity.

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  sync        Mirror a single repo ad-hoc (no config file needed).
  sync-all    Import and export all repositories defined in config.
  import-all  Clone or fetch all source repos into local mirrors.
  export-all  Push all local mirrors to their destinations.
```

### Common flags (sync-all / import-all / export-all)

| Flag | Default | Description |
|------|---------|-------------|
| `-c, --config` | required | Path to JSON config file |
| `--dry-run` | false | Print commands, do not execute |
| `--parallel N` | from config | Override worker count |
| `--timeout N` | from config | Per-repo timeout in seconds |
| `--verbose` | false | Enable DEBUG logging |

### sync (ad-hoc)

```bash
gitbit sync \
  --source <URL> \
  --dest   <URL> \
  [--name  NAME] \
  [--lfs] \
  [--mirrors-dir PATH] \
  [--dry-run] \
  [--timeout N] \
  [--verbose]
```

---

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | All repos succeeded |
| 1 | One or more repos failed, or a config error occurred |

---

## Contributing

Thank you for considering a contribution. This section covers the essentials.

### Code of Conduct

Be respectful and constructive. We follow the
[Contributor Covenant](https://www.contributor-covenant.org/) v2.1.

### Getting started

**1. Fork and clone**

```bash
git clone https://github.com/your-org/gitbit.git
cd gitbit
```

**2. Create a virtual environment and install dev dependencies**

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

**3. Install pre-commit hooks**

```bash
pre-commit install
```

Hooks run automatically on `git commit`: trailing whitespace, EOF fixer,
YAML/JSON checks, Black, isort, and flake8.

### Coding standards

| Tool | Config |
|------|--------|
| Formatter | `black` — line length 100 |
| Import sorter | `isort` — `black` profile |
| Linter | `flake8` — see `.flake8` |
| Type checker | `mypy --strict` |

- Use `from __future__ import annotations` in any module that uses `X | Y` union syntax.
- All subprocess calls must pass a **list** of arguments — never `shell=True`.
- Credentials must never appear in log output. Use `safe_url()` for any URL logged.
- New public functions should have a one-line docstring at minimum.

### Running tests

```bash
# All tests with coverage
pytest

# A single module
pytest tests/test_config.py -v

# With debug logging visible
pytest -s --log-cli-level=DEBUG
```

Coverage must remain at or above 90% for a PR to be accepted.

### Commit style

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add --format flag to sync command
fix: handle empty token_env in inject_https_token
chore: bump tenacity to 8.3
docs: update README with new config examples
test: cover DiskSpaceError path in clone_mirror
```

### Pull request process

1. Open an issue first for non-trivial changes.
2. Branch off `main`: `git checkout -b feat/my-feature`.
3. Write tests for any new behaviour or bug fix.
4. Ensure `flake8`, `mypy`, and `pytest` all pass locally.
5. Open a PR against `main` with a clear description of what and why.
6. At least one maintainer review is required before merging.

### Reporting security issues

Do **not** open a public issue for security vulnerabilities. Email
`security@example.com` with a description and reproduction steps.

---

## License

[MIT](LICENSE) — Copyright (c) 2026 Gitbit contributors.
