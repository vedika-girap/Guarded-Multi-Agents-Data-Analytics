from contextlib import asynccontextmanager
import sys
from uuid import uuid4

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.config import DATA_DIR, get_settings, validate_runtime_settings
from app.ingestion.seed import initialize


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        validate_runtime_settings()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    initialize()
    yield


app = FastAPI(title="Data Assistant", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.middleware("http")
async def request_id_middleware(request, call_next):
    request.state.request_id = uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"error_code": "HTTP_ERROR", "message": str(exc.detail)}
    body = {
        "error_code": detail.get("error_code", "HTTP_ERROR"),
        "message": detail.get("message", "The request could not be completed."),
        "request_id": getattr(request.state, "request_id", "unknown"),
    }
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, _: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error_code": "REQUEST_VALIDATION_ERROR",
            "message": "The request did not match the API schema.",
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    )


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "mode": "demo" if settings.demo_mode else settings.environment,
        "demo_mode": settings.demo_mode,
        "gemini_key_configured": settings.gemini_api_key is not None,
        "chroma_index_exists": (DATA_DIR / "chroma" / "chroma.sqlite3").is_file(),
    }
