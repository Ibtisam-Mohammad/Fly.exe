# SPDX-License-Identifier: GPL-2.0-or-later
"""Project-specific errors with actionable messages."""


class FlySimError(RuntimeError):
    """Base class for expected user-facing errors."""


class ConfigurationError(FlySimError):
    """Configuration or provenance metadata is invalid."""


class DatasetError(FlySimError):
    """Dataset acquisition or validation failed."""


class CausalityError(FlySimError):
    """A simulator component attempted to violate biological-time ordering."""


class ReadinessError(FlySimError):
    """A scientific command is gated by missing prerequisites."""

