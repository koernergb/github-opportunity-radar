"""Stable, sanitized API error responses."""

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@dataclass(frozen=True)
class ApiError(Exception):
    """An expected API failure safe to return to a browser."""

    status_code: int
    code: str
    message: str
    details: dict[str, Any] | None = None


def install_error_handlers(app: FastAPI) -> None:
    """Install handlers that never serialize exception text or secrets."""

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, error: ApiError) -> JSONResponse:
        return _response(request, error.status_code, error.code, error.message, error.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        del error
        return _response(request, 422, "request_invalid", "The request is invalid.")

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, error: Exception) -> JSONResponse:
        del error
        return _response(request, 500, "internal_error", "An unexpected error occurred.")


def _response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", None),
        }
    }
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=body)
