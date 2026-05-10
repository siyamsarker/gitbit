<div align="center">

# Gitbit

**Mirror Git repositories with full ref fidelity.**  
Branches, tags, notes, and LFS objects — all of it, exactly as-is.

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue?style=flat-square)](https://www.python.org/downloads/)
[![MIT License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000?style=flat-square)](https://github.com/psf/black)
[![Version](https://img.shields.io/badge/version-0.3.2-informational?style=flat-square)](https://github.com/siyamsarker/gitbit)

</div>

---

Gitbit is a command-line tool that mirrors Git repositories from a source host to a destination host — reliably, in bulk, and without manual intervention. It replicates every branch, tag, note, and internal ref, optionally including Git LFS objects. It was built for automated backup pipelines, cross-host repository replication, and disaster recovery setups where syncing only the default branch simply isn't good enough.

## How it works

```
Source repo                  Local mirror                   Destination repo
(GitHub, GitLab, ...)        (~/.gitbit/mirrors/)           (backup host, another forge, ...)

  git@github.com  ──── clone / fetch ────▶  /mirrors/ProjectA.git  ──── push --prune ────▶  git@backup.example.com
```

On the first run Gitbit clones the source as a bare mirror. Every run after that it fetches. Both the fetch and the push happen in parallel across all configured repositories.

---

**Contents**

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation) — [Uninstalling](#uninstalling) · [Updating](#updating)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Commands](#commands)
- [Sync State](#sync-state)
- [Log File](#log-file)
- [Authentication](#authentication)
- [Security](#security)
- [Exit Codes](#exit-codes)
- [Contributing](#contributing)
- [License](#license)

---

## Features

| Capability | Detail |
| :--- | :--- |
| **Full ref mirroring** | Replicates every branch, tag, note, and internal ref via explicit refspecs |
| **GitLab-safe push** | Excludes hidden refs (`refs/merge-requests/*`, `refs/pipelines/*`, etc.) that GitLab rejects on push |
| **Git LFS support** | Optionally transfers all LFS objects alongside the repository |
| **SSH & HTTPS auth** | SSH agent / key file, or HTTPS token injected from an environment variable |
| **Parallel execution** | Processes multiple repositories concurrently with a configurable worker limit |
| **Automatic retries** | Exponential backoff with jitter on transient network failures (up to 5 attempts) |
| **Auth fail-fast** | Wrong key or expired token fails in one attempt — never wastes all five retries |
| **Disk space guard** | Pre-flight check before cloning to prevent partial writes on full disks |
| **Dry-run mode** | Prints every git command without executing — safe for testing configuration |
| **Config validation** | Checks env vars, SSH key paths, and config structure without touching the network |
| **Mirror status** | Shows each repo's local mirror size and last-modified time at a glance |
| **Persistent sync state** | Records the outcome of every run; powers `--retry-failed` and the status display |
| **Flexible invocation** | Batch mode via JSON config file, or ad-hoc single-repo sync inline |

---

## Requirements

- **Python** 3.9 or later
- **Git** 2.29 or later — required for negative refspec support (`^refs/...`) used to exclude GitLab-internal hidden refs during push
- **git-lfs** _(optional)_ — only needed when mirroring repositories that contain LFS objects ([installation guide](https://git-lfs.com/))

---

## Installation

### Option A — pipx _(recommended)_

[pipx](https://pipx.pypa.io/) installs CLI tools in isolated Python environments so they don't interfere with your system packages.

**1. Install pipx**

| OS / Distro | Command |
| :--- | :--- |
| Debian / Ubuntu | `sudo apt install pipx` |
| Fedora / RHEL 8+ / CentOS Stream | `sudo dnf install pipx` |
| Arch / Manjaro | `sudo pacman -S python-pipx` |
| openSUSE Tumbleweed / Leap | `sudo zypper install python3-pipx` |
| Alpine Linux | `sudo apk add pipx` |
| macOS | `brew install pipx` |
| Other | `python3 -m pip install --user pipx` |

**2. Add pipx to your PATH**

```bash
pipx ensurepath
```

Restart your shell (or `source ~/.bashrc` / `source ~/.zshrc`) for the change to take effect.

**3. Install Gitbit**

```bash
pipx install git+https://github.com/siyamsarker/gitbit.git
gitbit --version
```

### Option B — Run from source

```bash
git clone https://github.com/siyamsarker/gitbit.git
cd gitbit
pip install -r requirements.txt
python -m gitbit --help
```

### Editable install (development)

```bash
git clone https://github.com/siyamsarker/gitbit.git
cd gitbit
pip install -e ".[dev]"
```


### Uninstalling

```bash
# pipx
pipx uninstall gitbit

# pip / editable install
pip uninstall gitbit

# source clone — just remove the directory
rm -rf /path/to/gitbit
```

### Updating

```bash
# pipx
pipx upgrade gitbit && gitbit --version

# editable install
cd /path/to/gitbit && git pull && pip install -e ".[dev]"

# source clone
cd /path/to/gitbit && git pull && pip install -r requirements.txt
```

> [!NOTE]
> On an editable install, most code changes take effect immediately after `git pull`. Reinstalling ensures any new entry points or dependencies in `pyproject.toml` are registered.

---

## Quick Start

Mirror a single repository — no config file needed:

```bash
gitbit sync \
  --source git@github.com:your-org/repo.git \
  --dest   git@backup.example.com:mirrors/repo.git
```

Mirror every repository defined in a config file:

```bash
gitbit sync-all --config repos.json
```

Preview exactly what would run without touching the network:

```bash
gitbit sync-all --config repos.json --dry-run
```

---

## Configuration

Gitbit reads repository definitions from a JSON file. Pass the path with `-c FILE` on every batch command.

### Creating repos.json

```bash
mkdir -p ~/.gitbit
$EDITOR ~/.gitbit/repos.json
```

Paste the minimal template below and fill in your values:

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
      "name":   "my-repo",
      "source": "git@github.com:your-org/your-repo.git",
      "dest":   "git@backup.example.com:mirrors/your-repo.git"
    }
  ]
}
```

Then pass the file to every command:

```bash
gitbit sync-all  -c ~/.gitbit/repos.json
gitbit validate  -c ~/.gitbit/repos.json
gitbit status    -c ~/.gitbit/repos.json
```

> [!WARNING]
> `repos.json` may contain SSH key paths and token environment variable names. Keep it out of version control. If you cloned the repo, it is already listed in `.gitignore`.

If you cloned the repo, there is also a ready-to-edit example:

```bash
cp repos.example.json repos.json
$EDITOR repos.json
```

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
| :--- | :--- | :--- | :--- |
| `parallel` | integer | `4` | Max repositories processed concurrently (1–32) |
| `timeout` | integer | `300` | Max seconds per git operation |
| `verbose` | boolean | `false` | Enable DEBUG-level logging |
| `mirrors_dir` | string | `~/.gitbit/mirrors` | Directory where bare mirror clones are stored |

### `repos[]` options

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `name` | string | Yes | Unique label used as the local mirror folder name |
| `source` | string | Yes | Source repository URL (SSH or HTTPS) |
| `dest` | string | Yes | Destination repository URL (SSH or HTTPS) |
| `auth` | object | No | Authentication config (see [Authentication](#authentication)) |
| `lfs` | boolean | No | Transfer Git LFS objects — default `false` |

---

## Commands

All commands accept `-h` or `--help` for detailed usage.

### `sync-all` — mirror all repositories

```bash
gitbit sync-all -c repos.json [OPTIONS]
```

Runs the complete mirroring pipeline for every repository in the config: clone or fetch from source, optionally fetch LFS objects, then push all refs to the destination.

| Option | Description |
| :--- | :--- |
| `--only NAME` | Process only this repo. Repeatable. Mutually exclusive with `--exclude` / `--retry-failed`. |
| `--exclude NAME` | Skip this repo. Repeatable. Mutually exclusive with `--only` / `--retry-failed`. |
| `--fail-fast` | Stop after the first failure; mark remaining repos as skipped. |
| `--retry-failed` | Re-run only repos that failed in the previous run. Mutually exclusive with `--only` / `--exclude`. |

### `import-all` — fetch sources only

```bash
gitbit import-all -c repos.json [OPTIONS]
```

Clones or fetches each source into the local mirror directory. Does **not** push to destinations. Useful for staging updates before a separate `export-all`, or when you want to inspect mirrors before distributing them.

Accepts the same `--only`, `--exclude`, `--fail-fast`, and `--retry-failed` options as `sync-all`.

### `export-all` — push to destinations only

```bash
gitbit export-all -c repos.json [OPTIONS]
```

Pushes each local mirror to its configured destination. Local mirrors must already exist — run `import-all` first, or use `sync-all` to do both in one step.

Accepts the same `--only`, `--exclude`, `--fail-fast`, and `--retry-failed` options as `sync-all`.

### `validate` — check config without network access

```bash
gitbit validate -c repos.json
```

Verifies your configuration before touching anything on the network. Checks:

- Valid JSON syntax and schema
- Duplicate repository names
- HTTPS token environment variables (must be set and non-empty)
- SSH private key files (must exist on disk)
- `mirrors_dir` accessibility (warning only if the directory doesn't exist yet)

Exits `0` if there are no errors. Warnings do not affect the exit code.

```
Validating repos.json
  2 repo(s) defined  |  mirrors_dir: /home/user/.gitbit/mirrors

  [error]  RepoB > auth.token_env: Environment variable 'GITLAB_TOKEN' is not set or empty

  1 error(s), 0 warning(s)
```

### `status` — inspect local mirrors

```bash
gitbit status -c repos.json
```

Shows each repository's local mirror directory, disk size, and time since last modification. No network connections are made.

```
Mirror status  —  repos.json
Mirrors directory: /home/user/.gitbit/mirrors

  NAME        MIRROR     SIZE         LAST MODIFIED    LAST SYNC    STATUS
  ----------  -------    ---------    --------------   ----------   -------
  ProjectA    present    142.3 MB     2h ago           2h ago       success
  RepoB       missing    —            —                never        —

  2 repo(s)  —  1 mirrored, 1 pending
```

**LAST SYNC** is the relative age of the last recorded sync attempt (from the state file). **STATUS** shows `success`, `failed`, or `—` (never run).

### `sync` — ad-hoc single repository

```bash
gitbit sync --source <URL> --dest <URL> [OPTIONS]
```

Mirrors a single repository without a config file. Credentials are picked up from the SSH agent or environment automatically.

| Option | Default | Description |
| :--- | :--- | :--- |
| `--source` | _(required)_ | Source repository URL |
| `--dest` | _(required)_ | Destination repository URL |
| `--name` | `adhoc` | Label for the local mirror directory |
| `--lfs` | off | Also mirror Git LFS objects |
| `--mirrors-dir` | `~/.gitbit/mirrors` | Directory for local mirror storage |
| `--dry-run` | off | Print commands without executing |
| `--timeout` | `300` | Max seconds per operation |
| `--verbose` | off | Enable DEBUG-level logging |

### Shared options _(all batch commands)_

| Option | Description |
| :--- | :--- |
| `-c FILE` | Path to the JSON configuration file _(required)_ |
| `--dry-run` | Print each git command without executing it |
| `--parallel N` | Override the `parallel` value from config |
| `--timeout SECONDS` | Override the `timeout` value from config |
| `--verbose` | Enable DEBUG-level logging |
| `--only NAME` | Process only the named repo(s); repeatable |
| `--exclude NAME` | Skip the named repo(s); repeatable |
| `--fail-fast` | Stop after the first failure |
| `--retry-failed` | Re-run only repos that failed last time |

---

## Sync State

Gitbit writes the outcome of every `sync-all`, `import-all`, and `export-all` run to:

```
~/.gitbit/state.json
```

For each repository it records the timestamp, success/failure status, error message (if any), and which command was responsible. This drives `--retry-failed` and populates the **LAST SYNC** / **STATUS** columns in `gitbit status`.

### State file format

```json
{
  "repos": {
    "ProjectA": {
      "last_sync_at":     "2026-05-08T10:30:12",
      "last_sync_status": "success",
      "last_error":       null,
      "last_command":     "sync-all"
    },
    "RepoB": {
      "last_sync_at":     "2026-05-08T10:31:05",
      "last_sync_status": "failed",
      "last_error":       "Connection timed out after 300s",
      "last_command":     "sync-all"
    }
  }
}
```

### Retrying failed repositories

After a partial run, re-run only the repos that failed without disturbing the ones that succeeded:

```bash
gitbit sync-all -c repos.json --retry-failed
```

If no failures are recorded in the state file, the command prints a message and exits `0`. If a previously failed repo is no longer in the config, it is warned about and skipped.

> [!NOTE]
> `--retry-failed` is mutually exclusive with `--only` and `--exclude`.

---

## Log File

Every command appends structured entries to `~/.gitbit/logs/gitbit.log`. The file rotates automatically at 5 MB with up to 5 backups kept (≤ 30 MB total on disk).

### `logs` — view and filter activity

```bash
gitbit logs [OPTIONS]
```

Reads `~/.gitbit/logs/gitbit.log` and all rotated backups. No config file required.

| Option | Default | Description |
| :--- | :--- | :--- |
| `-n N` / `--tail N` | `100` | Show the last N entries; `0` shows all |
| `--level LEVEL` | — | Minimum level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `--command CMD` | — | Filter by command: `sync-all`, `import-all`, `export-all`, `sync`, `validate`, `status` |
| `--repo NAME` | — | Show only entries mentioning this repository |
| `--since EXPR` | — | Entries from: `30m`, `2h`, `7d`, `2026-05-08`, `2026-05-08T10:30:00` |
| `-f` / `--follow` | off | Stream new entries live — Ctrl-C to stop |

**Examples:**

```bash
# Last 100 entries (default)
gitbit logs

# Errors only
gitbit logs --level ERROR

# All sync-all activity from the last 24 hours
gitbit logs --command sync-all --since 24h

# Everything for one repository
gitbit logs --repo "ProjectA"

# Errors for a specific repo since a date
gitbit logs --repo "ProjectA" --level ERROR --since 2026-05-08

# Follow the log live
gitbit logs -f

# Follow only sync-all errors, live
gitbit logs -f --command sync-all --level ERROR
```

**Sample output:**

```
2026-05-08T10:30:00 INFO     sync-all     Starting sync for 1 repo(s)
2026-05-08T10:30:01 INFO     sync-all     [ProjectA] Cloning mirror from git@github.com:org/ProjectA.git
2026-05-08T10:30:08 INFO     sync-all     [ProjectA] Pushing mirror to git@backup.example.com:mirrors/ProjectA.git
2026-05-08T10:30:12 INFO     sync-all     [ProjectA] Sync complete
2026-05-08T10:30:12 INFO     sync-all     Summary: 1 succeeded, 0 failed
2026-05-08T10:31:00 INFO     validate     Validating /root/.gitbit/repos.json
2026-05-08T10:31:00 INFO     validate     All checks passed.
```

---

## Authentication

### SSH

Gitbit sets `GIT_SSH_COMMAND` to force use of the specified key, with `StrictHostKeyChecking=accept-new` and `BatchMode=yes` for fully non-interactive operation. Key paths support `~` and environment variable expansion.

```json
{ "type": "ssh", "private_key": "~/.ssh/id_deploy" }
```

If no `auth` block is provided, Gitbit inherits the SSH agent and default keys from the calling environment — no configuration required for standard setups.

### HTTPS (token-based)

Export the environment variable referenced by `token_env` before running:

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

Credential safety and subprocess hygiene are first-class concerns in Gitbit.

- **No shell injection** — all subprocess calls use list arguments; `shell=True` is never used.
- **SSH key quoting** — key paths are shell-quoted via `shlex.quote()` before insertion into `GIT_SSH_COMMAND`, preventing issues with spaces or special characters.
- **Credential isolation** — HTTPS tokens are read from environment variables at runtime, not stored in the config file.
- **Log sanitisation** — tokens are stripped from every log message; they never appear in `--verbose` output.
- **Auth fail-fast** — authentication errors (wrong key, expired token, HTTP 401/403) bypass the retry loop entirely. A bad credential fails in one attempt, not five.
- **Config hygiene** — `repos.json` is in `.gitignore` by default. Do not commit it to version control.

---

## Exit Codes

| Code | Meaning |
| :--- | :--- |
| `0` | All repositories processed successfully |
| `1` | One or more repositories failed, or invalid input was provided |

Failed repositories are reported in the summary and do not interrupt processing of the rest of the batch.

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

---

## License

Released under the [MIT License](LICENSE).
