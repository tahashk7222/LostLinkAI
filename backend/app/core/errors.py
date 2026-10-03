import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("lostlink")


class AppError(Exception):
    """Expected, user-facing error. Message is safe to show to the client."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message


def not_found(what: str = "Resource") -> AppError:
    return AppError(404, f"{what} not found")


def forbidden(message: str = "You do not have access to this resource") -> AppError:
    return AppError(403, message)


def conflict(message: str) -> AppError:
    return AppError(409, message)


def bad_request(message: str) -> AppError:
    return AppError(400, message)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Technical details go to server logs only, never to the client.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})
