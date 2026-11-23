"""What can go wrong in a service, independent of HTTP.

Each class maps to one HTTP status in the app's error table; ``code`` is the
stable machine name the API puts in its error body (``project_not_found``).
"""


class ServiceError(Exception):
    code = "error"

    def __init__(self, detail: str = "", *, code: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code


class NotFound(ServiceError):  # 404 -- also for things the caller may not see
    code = "not_found"


class PermissionDenied(ServiceError):  # 403
    code = "forbidden"


class InvalidCredentials(ServiceError):  # 401
    code = "invalid_credentials"


class InvalidToken(ServiceError):  # 401
    code = "invalid_token"


class AccountDisabled(ServiceError):  # 403
    code = "account_disabled"


class AlreadyExists(ServiceError):  # 409
    code = "already_exists"


class Busy(ServiceError):  # 409 -- something is already in progress
    code = "busy"


class InvalidInput(ServiceError):  # 422
    code = "invalid_input"

    def __init__(
        self,
        detail: str = "",
        *,
        code: str | None = None,
        fields: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail, code=code)
        self.fields = fields or {}


class FileTooLarge(ServiceError):  # 413
    code = "file_too_large"


class NotReady(ServiceError):  # 503
    code = "not_ready"
