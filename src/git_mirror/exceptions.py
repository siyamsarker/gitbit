"""Exception hierarchy for git-mirror."""


class GitMirrorError(Exception):
    """Base exception for all git-mirror errors."""


class ConfigError(GitMirrorError):
    """Raised when configuration is invalid or missing."""


class GitOperationError(GitMirrorError):
    """Raised when a git subprocess command fails."""


class AuthError(GitMirrorError):
    """Raised when authentication setup fails."""


class DiskSpaceError(GitMirrorError):
    """Raised when there is insufficient disk space to proceed."""
