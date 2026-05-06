# Contributing to git-mirror

Thank you for considering a contribution. This document covers the essentials.

## Code of Conduct

Be respectful and constructive. We follow the
[Contributor Covenant](https://www.contributor-covenant.org/) v2.1.

## Getting started

### 1. Fork and clone

```bash
git clone https://github.com/your-org/git-mirror.git
cd git-mirror
```

### 2. Create a virtual environment and install dev dependencies

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 3. Install pre-commit hooks

```bash
pre-commit install
```

Hooks run automatically on `git commit`: trailing whitespace, EOF fixer,
YAML/JSON checks, Black, isort, and flake8.

## Coding standards

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

## Running tests

```bash
# All tests with coverage
pytest

# A single module
pytest tests/test_config.py -v

# With debug logging visible
pytest -s --log-cli-level=DEBUG
```

Coverage must remain at or above 90% for a PR to be accepted.

## Commit style

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add --format flag to sync command
fix: handle empty token_env in inject_https_token
chore: bump tenacity to 8.3
docs: update README with new config examples
test: cover DiskSpaceError path in clone_mirror
```

## Pull request process

1. Open an issue first for non-trivial changes.
2. Branch off `main`: `git checkout -b feat/my-feature`.
3. Write tests for any new behaviour or bug fix.
4. Ensure `flake8`, `mypy`, and `pytest` all pass locally.
5. Open a PR against `main` with a clear description of what and why.
6. At least one maintainer review is required before merging.

## Reporting security issues

Do **not** open a public issue for security vulnerabilities. Email
`security@example.com` with a description and reproduction steps.
