"""Web service domain errors."""


class WebServiceError(ValueError):
    """Base error for web client business operations."""


class BadRequestError(WebServiceError):
    """Raised when a request payload is invalid."""


class NotFoundError(WebServiceError):
    """Raised when a requested resource does not exist."""


class AttachmentError(BadRequestError):
    """Raised when an attachment operation fails validation."""


class AttachmentTooLargeError(AttachmentError):
    """Raised when an uploaded attachment exceeds size limits."""
