class OpenAICodexAuthError(RuntimeError):
    """Base error for OpenAI Codex OAuth."""


class OpenAICodexProfileNotFound(OpenAICodexAuthError):
    """Raised when no matching OAuth profile exists."""


class OpenAICodexReauthRequiredError(OpenAICodexAuthError):
    """Raised when refresh fails and the user must sign in again."""


class OpenAICodexOAuthStateError(OpenAICodexAuthError):
    """Raised when the OAuth callback state is missing or invalid."""

