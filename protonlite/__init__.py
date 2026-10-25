"""A small MIT-licensed client for Proton Mail, plus the Hermes tools built on it.

The protocol work is a port of Proton's own MIT Go libraries; see
THIRD-PARTY-NOTICES.md. Nothing here is derived from GPL sources.
"""

from .errors import (
    APIError,
    AuthError,
    HumanVerificationRequired,
    ProtonError,
    SessionExpired,
    TwoFactorRequired,
)

__version__ = "0.28.0"

__all__ = [
    "APIError",
    "AuthError",
    "HumanVerificationRequired",
    "ProtonError",
    "SessionExpired",
    "TwoFactorRequired",
    "__version__",
]
