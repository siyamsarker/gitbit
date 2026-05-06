# git-mirror

[![CI](https://github.com/your-org/git-mirror/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/git-mirror/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/git-mirror)](https://pypi.org/project/git-mirror/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/git-mirror)](https://pypi.org/project/git-mirror/)

A production-ready CLI tool for mirroring Git repositories with **full ref fidelity** — all
branches, tags, and notes are preserved. Supports SSH and HTTPS authentication, Git LFS, concurrent
syncing, automatic retries, and Docker deployment.

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
pip install git-mirror
```

Requires Python ≥ 3.9, `git` in `$PATH`, and (optionally) `git-lfs`.

### Docker

```bash
docker pull ghcr.io/your-org/git-mirror:latest

docker run --rm \
  -v "$HOME/.ssh:/root/.ssh:ro" \
  -v "$(pwd)/repos.json:/app/repos.json:ro" \
  -v "$HOME/.git-mirror:/root/.git-mirror" \
  ghcr.io/your-org/git-mirror:latest \
  sync-all -c /app/repos.json
```

### From source

```bash
git clone https://github.com/your-org/git-mirror.git
cd git-mirror
pip install -e ".[dev]"
```

---

## Quick start

### Ad-hoc single repo (no config file)

```bash
git-mirror sync \
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
git-mirror sync-all -c repos.json

# Or split the two phases
git-mirror import-all -c repos.json
git-mirror export-all -c repos.json
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
    "mirrors_dir": "~/.git-mirror/mirrors"  // local mirror storage root
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
Usage: git-mirror [OPTIONS] COMMAND [ARGS]...

  git-mirror — mirror Git repositories with full ref fidelity.

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
git-mirror sync \
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

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

[MIT](LICENSE) — Copyright (c) 2026 git-mirror contributors.
