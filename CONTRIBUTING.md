# Contributing to Gitbit

Thank you for your interest in contributing. Please read this guide before opening a PR.

## Development setup

```bash
git clone https://github.com/siyamsarker/gitbit.git
cd gitbit
pip install -e ".[dev]"
```

This installs gitbit in editable mode along with all development dependencies (pytest, mypy, flake8, black, isort).

## Running the tests

```bash
python -m pytest
```

The test suite runs with coverage enabled by default (configured in `pyproject.toml`). All 100+ tests must pass and coverage must remain at 99%+ before a PR is merged.

## Code style

The project uses [Black](https://black.readthedocs.io/) for formatting and [isort](https://pycog.readthedocs.io/en/stable/isort.html) for import ordering. Run both before committing:

```bash
black gitbit/ tests/
isort gitbit/ tests/
```

## Type checking

Strict [mypy](https://mypy.readthedocs.io/) is required:

```bash
mypy gitbit/
```

All public functions must have full type annotations.

## Linting

```bash
flake8 gitbit/ tests/
```

Line length is 100 characters (see `.flake8`).

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add support for per-repo auth overrides
fix: quote SSH key path in GIT_SSH_COMMAND
chore: update dependencies
docs: expand authentication section in README
test: add edge cases for safe_url with custom ports
```

## Submitting a pull request

1. Fork the repository and create a branch from `main`.
2. Make your changes with tests covering the new behaviour.
3. Ensure `pytest`, `mypy`, `flake8`, `black --check`, and `isort --check` all pass.
4. Open a PR against `main` with a clear description of what changed and why.

## Security issues

Please do **not** open a public issue for security vulnerabilities. Email the maintainer directly (see the repository contact) so the issue can be assessed and patched before public disclosure.
