<p align="center">
  <h1 align="center">Gitbit</h1>
  <p align="center">Mirror Git repositories with full ref fidelity — branches, tags, notes, and LFS objects.</p>
  <p align="center">
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9%2B-blue?style=flat-square" alt="Python 3.9+"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="MIT License"></a>
    <a href="https://github.com/psf/black"><img src="https://img.shields.io/badge/code%20style-black-000000?style=flat-square" alt="Code style: black"></a>
    <a href="https://github.com/siyamsarker/gitbit"><img src="https://img.shields.io/badge/version-0.1.0-informational?style=flat-square" alt="Version 0.1.0"></a>
  </p>
</p>

---

Gitbit is a command-line tool for mirroring Git repositories with exact ref fidelity. It uses `git clone --mirror` and `git push --mirror` to replicate every branch, tag, note, and internal ref from a source to a destination — not just the default branch. It is designed for automated backup pipelines, cross-host repository replication, and disaster recovery workflows.

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Commands](#commands)
- [Authentication](#authentication)
- [Security](#security)
- [Exit Codes](#exit-codes)
- [Contributing](#contributing)
- [License](#license)

---

---

## Features

| Capability | Detail |
|---|---|
| **Full ref mirroring** | Replicates every branch, tag, note, and internal ref via `--mirror` |
| **Git LFS support** | Optionally transfers all LFS objects alongside the repository |
| **SSH & HTTPS auth** | SSH agent / key file, or HTTPS token injected from an environment variable |
| **Parallel execution** | Processes multiple repositories concurrently with a configurable worker limit |
| **Automatic retries** | Exponential backoff with jitter on transient network failures (up to 5 attempts); auth failures fail immediately without retrying |
| **Disk space guard** | Pre-flight check before cloning to prevent partial writes on full disks |
| **Dry-run mode** | Prints every git command without executing — safe for testing configuration |
| **Config validation** | Checks env vars, SSH key paths, and config structure without touching the network |
| **Mirror status** | Shows each repo's local mirror size and last-modified time at a glance |
| **Flexible invocation** | Batch mode via JSON config file, or ad-hoc single-repo mirroring inline |

---

## Requirements

- **Python** 3.9 or later
- **Git** 2.x
- **git-lfs** _(optional)_ — required only when mirroring repositories with LFS objects ([installation guide](https://git-lfs.com/))

---

## Installation

### Option A — Install via pip _(recommended)_

```bash
pip install git+https://github.com/siyamsarker/gitbit.git
```

Verify the installation:

```bash
gitbit --version
```

For a local editable install during development:

```bash
git clone https://github.com/siyamsarker/gitbit.git
cd gitbit
pip install -e ".[dev]"
```

### Option B — Run from source

```bash
git clone https://github.com/siyamsarker/gitbit.git
cd gitbit
pip install -r requirements.txt
python -m gitbit --help
```

---

## Quick Start

**Mirror a single repository — no config file required:**

```bash
gitbit sync \
  --source git@github.com:your-org/repo.git \
  --dest   git@backup.example.com:mirrors/repo.git
```

**Mirror all repositories defined in a config file:**

```bash
gitbit sync-all --config repos.json
```

**Preview what would run without executing anything:**

```bash
gitbit sync-all --config repos.json --dry-run
```

---

## Configuration

Gitbit reads repository definitions from a JSON file. Use the provided example as a starting point:

```bash
cp repos.example.json repos.json
$EDITOR repos.json
```

> **Note:** `repos.json` may contain sensitive paths and environment variable names. It is listed in `.gitignore` by default and should never be committed to version control.

### Full configuration reference

```json
{
  "global": {
    "parallel":    4,
    "timeout":     300,
    "verbose":     false,
    "mirrors_dir": "~/.gitbit/mirrors"
  },
  "repos": [
    {
      "name":   "ProjectA",
      "source": "git@github.com:org/ProjectA.git",
      "dest":   "git@backup.example.com:mirrors/ProjectA.git",
      "auth":   { "type": "ssh", "private_key": "~/.ssh/id_rsa" },
      "lfs":    true
    },
    {
      "name":   "RepoB",
      "source": "https://gitlab.com/team/RepoB.git",
      "dest":   "https://git.example.com/team/RepoB.git",
      "auth":   { "type": "https", "token_env": "GITLAB_TOKEN" },
      "lfs":    false
    }
  ]
}
```

### `global` options

| Field | Type | Default | Description |
|---|---|---|---|
| `parallel` | integer | `4` | Maximum number of repositories processed concurrently (1–32) |
| `timeout` | integer | `300` | Maximum seconds allowed per git operation |
| `verbose` | boolean | `false` | Enable DEBUG-level logging |
| `mirrors_dir` | string | `~/.gitbit/mirrors` | Directory where bare mirror clones are stored |

### `repos[]` options

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | Yes | Unique label used as the local mirror folder name |
| `source` | string | Yes | Source repository URL (SSH or HTTPS) |
| `dest` | string | Yes | Destination repository URL (SSH or HTTPS) |
| `auth` | object | No | Authentication configuration (see [Authentication](#authentication)) |
| `lfs` | boolean | No | Transfer Git LFS objects — default `false` |

---

## Commands

All commands accept `-h` or `--help` for detailed usage information.

### `sync-all` — full pipeline for all repositories

```bash
gitbit sync-all -c repos.json [OPTIONS]
```

Runs the complete mirroring pipeline for every repository defined in the config: clone or fetch from source, optionally fetch LFS objects, then push all refs to the destination.

### `import-all` — fetch sources only

```bash
gitbit import-all -c repos.json [OPTIONS]
```

Clones or fetches each source repository into the local mirror directory. Does **not** push to destinations. Use this to stage updates before a separate `export-all` step, or when you need to inspect mirrors before distributing them.

### `export-all` — push to destinations only

```bash
gitbit export-all -c repos.json [OPTIONS]
```

Pushes each local mirror to its configured destination. Local mirrors must already exist — run `import-all` first, or use `sync-all` to perform both steps in one command.

### `validate` — check configuration without network access

```bash
gitbit validate -c repos.json
```

Verifies the configuration file before running any sync operations. Checks for:

- Valid JSON syntax and schema
- Duplicate repository names
- HTTPS token environment variables (must be set and non-empty)
- SSH private key files (must exist on disk)
- `mirrors_dir` accessibility (warning if the directory does not yet exist)

Exits `0` if no errors are found. Warnings do not affect the exit code.

```
Validating repos.json
  2 repo(s) defined  |  mirrors_dir: /home/user/.gitbit/mirrors

  [error]  RepoB > auth.token_env: Environment variable 'GITLAB_TOKEN' is not set or empty

  1 error(s), 0 warning(s)
```

### `status` — show local mirror state

```bash
gitbit status -c repos.json
```

Displays each repository's local mirror directory, total size on disk, and time since last modification. No network connections are made.

```
Mirror status  —  repos.json
Mirrors directory: /home/user/.gitbit/mirrors

  NAME        MIRROR     SIZE         LAST MODIFIED
  ----------  -------    ---------    --------------------
  ProjectA    present    142.3 MB     2h ago
  RepoB       missing    —            —

  2 repo(s)  —  1 mirrored, 1 pending
```

### `sync` — ad-hoc single repository

```bash
gitbit sync --source <URL> --dest <URL> [OPTIONS]
```

Mirrors a single repository without requiring a config file. Credentials are picked up from the SSH agent or environment variables automatically.

| Option | Default | Description |
|---|---|---|
| `--source` | _(required)_ | Source repository URL |
| `--dest` | _(required)_ | Destination repository URL |
| `--name` | `adhoc` | Label for the local mirror directory |
| `--lfs` | off | Also mirror Git LFS objects |
| `--mirrors-dir` | `~/.gitbit/mirrors` | Directory for local mirror storage |
| `--dry-run` | off | Print commands without executing |
| `--timeout` | `300` | Maximum seconds per operation |
| `--verbose` | off | Enable DEBUG-level logging |

### Shared options _(all batch commands)_

| Option | Description |
|---|---|
| `-c FILE` | Path to the JSON configuration file _(required)_ |
| `--dry-run` | Print each git command without executing it |
| `--parallel N` | Override the `parallel` value from config |
| `--timeout SECONDS` | Override the `timeout` value from config |
| `--verbose` | Enable DEBUG-level logging |

---

## Authentication

### SSH

Gitbit sets `GIT_SSH_COMMAND` to use the specified private key with `StrictHostKeyChecking=accept-new` and `BatchMode=yes`, ensuring fully non-interactive operation. Key paths support `~` and environment variable expansion.

If no `auth` block is provided, Gitbit inherits the SSH agent and default keys from the calling environment.

```json
{ "type": "ssh", "private_key": "~/.ssh/id_deploy" }
```

### HTTPS (token-based)

Set the environment variable referenced by `token_env` before invoking Gitbit:

```bash
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
gitbit sync-all -c repos.json
```

```json
{ "type": "https", "token_env": "GITHUB_TOKEN" }
```

The token is read from the environment at runtime, injected into the URL as `oauth2:<token>@host`, and never written to disk or printed in logs.

---

## Security

Gitbit is designed with credential safety and subprocess hygiene as first-class concerns.

- **No shell injection** — all subprocess calls use list arguments; `shell=True` is never used.
- **SSH key path quoting** — key paths are shell-quoted via `shlex.quote()` before being placed in `GIT_SSH_COMMAND`, preventing issues with spaces or special characters.
- **Credential isolation** — HTTPS tokens are read from environment variables at runtime, not stored in the config file.
- **Log sanitisation** — credentials are stripped from every log message before output; tokens never appear in `--verbose` traces.
- **Auth failures fail immediately** — authentication errors (wrong key, expired token, HTTP 401/403) are detected from git's stderr and raised as a distinct exception that bypasses the retry loop. A bad credential fails in one attempt, not five.
- **Config file hygiene** — `repos.json` is listed in `.gitignore` by default. Do not commit it to version control.

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | All repositories processed successfully |
| `1` | One or more repositories failed, or invalid input was provided |

Failed repositories are reported in the summary output and do not interrupt processing of other repositories in the batch.

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

---

## License

Released under the [MIT License](LICENSE).
