# SPDX-License-Identifier: GPL-2.0-or-later
"""Project-specific errors with actionable messages."""


class FlySimError(RuntimeError):
    """Base class for expected user-facing errors."""

    default_code = "FLYSIM_ERROR"
    default_retryable = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code or self.default_code
        self.retryable = self.default_retryable if retryable is None else retryable


class ConfigurationError(FlySimError):
    """Configuration or provenance metadata is invalid."""


class DatasetError(FlySimError):
    """Dataset acquisition or validation failed."""

    default_code = "DATASET_ERROR"


class ContactImportRecycle(DatasetError):
    """A contact import checkpoint is safe and the worker should be recycled."""

    default_code = "CONTACT_IMPORT_RECYCLE"
    default_retryable = True


class CausalityError(FlySimError):
    """A simulator component attempted to violate biological-time ordering."""


class ReadinessError(FlySimError):
    """A scientific command is gated by missing prerequisites."""


class ValidationError(FlySimError):
    """Evidence is incomplete, malformed, or insufficient for a claimed tier."""

    default_code = "VALIDATION_ERROR"
