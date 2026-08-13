from __future__ import annotations


class AdminError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class AdminAuthenticationError(AdminError):
    def __init__(self, message: str = "Admin authentication failed") -> None:
        super().__init__("admin_authentication", message, status_code=401)


class AdminAuthorizationError(AdminError):
    def __init__(self, message: str = "Admin action is not allowed") -> None:
        super().__init__("admin_authorization", message, status_code=403)


class AdminConflictError(AdminError):
    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__("admin_conflict", message, status_code=409, details=details)


class AdminNotFoundError(AdminError):
    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(
            "admin_not_found",
            f"{resource} not found",
            status_code=404,
            details={"resource": resource, "identifier": identifier},
        )


class AdminValidationError(AdminError):
    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__("admin_validation", message, status_code=422, details=details)
