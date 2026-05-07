<p align="center">
  <h1 align="center">Gitbit</h1>
  <p align="center">Mirror Git repositories with full ref fidelity — branches, tags, notes, and LFS objects.</p>
  <p align="center">
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9%2B-blue?style=flat-square" alt="Python 3.9+"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="MIT License"></a>
    <a href="https://github.com/psf/black"><img src="https://img.shields.io/badge/code%20style-black-000000?style=flat-square" alt="Code style: black"></a>
    <a href="https://github.com/siyamsarker/gitbit"><img src="https://img.shields.io/badge/version-0.2.0-informational?style=flat-square" alt="Version 0.1.0"></a>
  </p>
</p>

---

Gitbit is a command-line tool for mirroring Git repositories with exact ref fidelity. It uses `git clone --mirror` and `git push --mirror` to replicate every branch, tag, note, and internal ref from a source to a destination — not just the default branch. It is designed for automated backup pipelines, cross-host repository replication, and disaster recovery workflows.

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Uninstallation](#uninstallation)
- [Updating](#updating)
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
- **Git** 2.29 or later — required for negative refspec support (`^refs/...`) used to exclude GitLab-internal hidden refs during push
- **git-lfs** _(optional)_ — required only when mirroring repositories with LFS objects ([installation guide](https://git-lfs.com/))

---

## Installation

### Option A — Install via pipx _(recommended)_

[pipx](https://pipx.pypa.io/) installs CLI tools in isolated environments, keeping them separate from your system Python.

**Step 1 — Install pipx**

| Distro / OS | Command |
|---|---|
| Debian / Ubuntu | `sudo apt install pipx` |
| Fedora / RHEL 8+ / CentOS Stream | `sudo dnf install pipx` |
| Arch / Manjaro | `sudo pacman -S python-pipx` |
| openSUSE Tumbleweed / Leap | `sudo zypper install python3-pipx` |
| Alpine Linux | `sudo apk add pipx` |
| macOS | `brew install pipx` |
| Other (generic) | `python3 -m pip install --user pipx` |

**Step 2 — Add pipx to your PATH**

```bash
pipx ensurepath
```

Restart your shell (or run `source ~/.bashrc` / `source ~/.zshrc`) for the PATH change to take effect.

**Step 3 — Install Gitbit**

```bash
pipx install git+https://github.com/siyamsarker/gitbit.git
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

## Uninstallation

### Installed via pipx

```bash
pipx uninstall gitbit
```

### Installed via pip (development / editable)

```bash
pip uninstall gitbit
```

### Run from source

Delete the cloned directory:

```bash
rm -rf /path/to/gitbit
```

---

## Updating

### Installed via pipx _(recommended)_

```bash
pipx upgrade gitbit
```

Verify the new version:

```bash
gitbit --version
```

### Installed via pip (development / editable)

Pull the latest code and reinstall in-place:

```bash
cd /path/to/gitbit
git pull
pip install -e ".[dev]"
```

The editable install means most code changes take effect immediately after `git pull`, but reinstalling ensures any new entry points or dependencies declared in `pyproject.toml` are picked up.

### Run from source

```bash
cd /path/to/gitbit
git pull
pip install -r requirements.txt
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

Gitbit reads repository definitions from a JSON file. You pass the file path to every batch command with `-c FILE`.

### Creating repos.json

**Installed via pipx** — create the file from scratch in a directory of your choice (e.g. `~/.gitbit/`):

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

Then pass the path explicitly to every command:

```bash
gitbit sync-all -c ~/.gitbit/repos.json
gitbit validate  -c ~/.gitbit/repos.json
gitbit status    -c ~/.gitbit/repos.json
```

**Installed from source** — copy the bundled example file:

```bash
cp repos.example.json repos.json
$EDITOR repos.json
```

> **Security note:** `repos.json` may contain SSH key paths and environment variable names for tokens. Keep it out of version control — if you cloned the repo, it is already listed in `.gitignore`.

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

| Option | Description |
|---|---|
| `--only NAME` | Process only this repo. Repeatable. Mutually exclusive with `--exclude`/`--retry-failed`. |
| `--exclude NAME` | Skip this repo. Repeatable. Mutually exclusive with `--only`/`--retry-failed`. |
| `--fail-fast` | Stop after the first failure; mark remaining repos as skipped. |
| `--retry-failed` | Re-run only repos that failed in the previous run. Mutually exclusive with `--only`/`--exclude`. |

### `import-all` — fetch sources only

```bash
gitbit import-all -c repos.json [OPTIONS]
```

Clones or fetches each source repository into the local mirror directory. Does **not** push to destinations. Use this to stage updates before a separate `export-all` step, or when you need to inspect mirrors before distributing them.

| Option | Description |
|---|---|
| `--only NAME` | Process only this repo. Repeatable. Mutually exclusive with `--exclude`/`--retry-failed`. |
| `--exclude NAME` | Skip this repo. Repeatable. Mutually exclusive with `--only`/`--retry-failed`. |
| `--fail-fast` | Stop after the first failure; mark remaining repos as skipped. |
| `--retry-failed` | Re-run only repos that failed in the previous run. Mutually exclusive with `--only`/`--exclude`. |

### `export-all` — push to destinations only

```bash
gitbit export-all -c repos.json [OPTIONS]
```

Pushes each local mirror to its configured destination. Local mirrors must already exist — run `import-all` first, or use `sync-all` to perform both steps in one command.

| Option | Description |
|---|---|
| `--only NAME` | Process only this repo. Repeatable. Mutually exclusive with `--exclude`/`--retry-failed`. |
| `--exclude NAME` | Skip this repo. Repeatable. Mutually exclusive with `--only`/`--retry-failed`. |
| `--fail-fast` | Stop after the first failure; mark remaining repos as skipped. |
| `--retry-failed` | Re-run only repos that failed in the previous run. Mutually exclusive with `--only`/`--exclude`. |

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

  NAME        MIRROR     SIZE         LAST MODIFIED           LAST SYNC    STATUS
  ----------  -------    ---------    --------------------    ----------   -------
  ProjectA    present    142.3 MB     2h ago                  2h ago       success
  RepoB       missing    —            —                       never        —

  2 repo(s)  —  1 mirrored, 1 pending
```

The **LAST SYNC** column shows the relative age of the last recorded sync attempt (from the state file), and **STATUS** shows whether it ended in `success`, `failed`, or `—` (never run).

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
| `--only NAME` | Process only the named repo(s); repeatable |
| `--exclude NAME` | Skip the named repo(s); repeatable |
| `--fail-fast` | Stop after the first failure |
| `--retry-failed` | Re-run only repos that failed last time |

---

## Sync State

Gitbit writes the outcome of every `sync-all`, `import-all`, and `export-all` run to a JSON state file at:

```
~/.gitbit/state.json
```

The state file records, for each repository, the timestamp of the last operation, whether it succeeded or failed, the error message (if any), and which command ran it. This information drives the `--retry-failed` flag and populates the **LAST SYNC** and **STATUS** columns in `gitbit status`.

### State file format

```json
{
  "repos": {
    "ProjectA": {
      "last_sync_at": "2026-05-08T10:30:12",
      "last_sync_status": "success",
      "last_error": null,
      "last_command": "sync-all"
    },
    "RepoB": {
      "last_sync_at": "2026-05-08T10:31:05",
      "last_sync_status": "failed",
      "last_error": "Connection timed out after 300s",
      "last_command": "sync-all"
    }
  }
}
```

### Retrying failed repositories

After a partial failure, re-run only the repos that failed without touching the ones that succeeded:

```bash
gitbit sync-all -c repos.json --retry-failed
```

If no failures are recorded in the state file, the command prints a message and exits 0. If a previously failed repo is no longer defined in the config, it is warned about and skipped.

`--retry-failed` is mutually exclusive with `--only` and `--exclude`.

---

## Log File

Every command writes a structured entry to `~/.gitbit/logs/gitbit.log`. The file rotates automatically at 5 MB and up to 5 backups are kept (≤ 30 MB total).

### `logs` — view and filter the activity log

```bash
gitbit logs [OPTIONS]
```

Reads `~/.gitbit/logs/gitbit.log` and all rotated backups. No config file required.

| Option | Default | Description |
|---|---|---|
| `-n N` / `--tail N` | `100` | Show the last N entries; `0` shows all |
| `--level LEVEL` | — | Minimum level to show: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `--command CMD` | — | Filter by command: `sync-all`, `import-all`, `export-all`, `sync`, `validate`, `status` |
| `--repo NAME` | — | Show only entries mentioning this repository name |
| `--since EXPR` | — | Show entries from this point: `30m`, `2h`, `7d`, `2026-05-08`, `2026-05-08T10:30:00` |
| `-f` / `--follow` | off | Stream new entries live — Ctrl-C to stop |

**Examples:**

```bash
# Last 100 entries (default)
gitbit logs

# Show only errors
gitbit logs --level ERROR

# Show all sync-all activity from the last 24 hours
gitbit logs --command sync-all --since 24h

# Show all activity for one repository
gitbit logs --repo "Test Project"

# Show errors for a specific repo since a date
gitbit logs --repo "Test Project" --level ERROR --since 2026-05-08

# Follow the log live
gitbit logs -f

# Follow only sync-all errors live
gitbit logs -f --command sync-all --level ERROR
```

**Sample log output:**

```
2026-05-08T10:30:00 INFO     sync-all     Starting sync for 1 repo(s)
2026-05-08T10:30:01 INFO     sync-all     [Test Project] Cloning mirror from git@vcs.example.com:org/repo.git
2026-05-08T10:30:08 INFO     sync-all     [Test Project] Pushing mirror to git@vcs.example.com:mirrors/repo.git
2026-05-08T10:30:12 INFO     sync-all     [Test Project] Sync complete
2026-05-08T10:30:12 INFO     sync-all     Summary: 1 succeeded, 0 failed
2026-05-08T10:31:00 INFO     validate     Validating /root/.gitbit/repos.json
2026-05-08T10:31:00 INFO     validate     All checks passed.
2026-05-08T10:32:00 INFO     status       Mirror status — /root/.gitbit/repos.json
```

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
