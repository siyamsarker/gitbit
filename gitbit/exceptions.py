"""
Custom exception hierarchy for gitbit.

All gitbit-specific exceptions inherit from GitMirrorError, which makes it
easy for callers to handle any internal error with a single except clause:

    try:
        sync_repo(...)
    except GitMirrorError as e:
        log_and_exit(e)

Each subclass represents a distinct failure category with different handling:

  ConfigError       — Bad input before any git work starts. Fix the config file.
  GitOperationError — Transient git failure. Retried automatically (up to 5x).
  AuthError         — Credential failure. NOT retried; bad creds always fail.
  DiskSpaceError    — Pre-flight guard triggered. Free up disk before retrying.

Exception hierarchy:
    GitMirrorError
    ├── ConfigError
    ├── GitOperationError
    ├── AuthError
    └── DiskSpaceError
"""


class GitMirrorError(Exception):
    """Base class for all gitbit-specific exceptions.

    Catching this type handles any error raised by this package without
    needing to import every subclass individually. Use a subclass when
    you need to distinguish error categories (e.g. auth vs. network).
    """


class ConfigError(GitMirrorError):
    """Raised when the configuration file cannot be loaded or is structurally invalid.

    Common causes:
      - The file path does not exist on disk.
      - The file contains invalid JSON.
      - The JSON structure fails Pydantic schema validation (e.g. a required
        field is missing, 'parallel' is out of the 1–32 range, wrong type).

    This error is raised by load_config() before any network activity begins.
    Fix the config file and re-run; no retry logic applies.
    """


class GitOperationError(GitMirrorError):
    """Raised when a git subprocess command exits with a non-zero return code.

    Covers transient, potentially recoverable failures such as:
      - Network timeout or connection reset mid-transfer.
      - Remote server temporarily unavailable (5xx errors).
      - Protocol-level errors that may succeed on a subsequent attempt.

    This exception is retryable. The tenacity decorator in _retryable_run()
    (git_ops.py) will attempt the same command up to 5 times with exponential
    backoff before re-raising.

    Note: Authentication failures raise AuthError (a sibling class, NOT a
    subclass) so the retry decorator can distinguish them and skip retrying.
    """


class AuthError(GitMirrorError):
    """Raised when authentication fails or cannot be configured.

    Common causes:
      - SSH private key file does not exist or is not readable.
      - The environment variable referenced by token_env is unset or empty.
      - Git reports 'Authentication failed' or 'Permission denied' in stderr.
      - The remote returns HTTP 401 or HTTP 403.

    This exception intentionally bypasses all retry logic. Retrying a bad
    credential will always fail and may trigger rate-limiting or account
    lockouts on the remote. Fix the credential and re-run.
    """


class DiskSpaceError(GitMirrorError):
    """Raised when there is insufficient free disk space to begin a clone.

    gitbit checks that at least MIN_FREE_GB (default 1 GB) is available on
    the filesystem that will hold the mirror before running git clone --mirror.
    This prevents partial clones that consume space but leave an unusable,
    corrupted mirror directory behind.

    Free up disk space and re-run; the clone will restart from scratch.
    """
