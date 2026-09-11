"""Errors raised by the FRET state-machine converter."""


class ConversionError(ValueError):
    """Raised when the input cannot be converted without changing its meaning."""


class ExpressionSyntaxError(ConversionError):
    """Raised when a supported FRET Boolean expression cannot be parsed."""

