import logging
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.auth import get_current_user
from app.database import Base, SessionLocal, engine
from app.models import User
from app.routers import dashboard, jobs, queues, users

# Automatically spin up DB tables in Docker on boot
Base.metadata.create_all(bind=engine)

logger = logging.getLogger("scheduler_api")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Distributed Job Scheduler Engine")


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "request_completed method=%s path=%s status=%s duration_ms=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "HTTP_ERROR",
            "detail": exc.detail,
            "path": request.url.path,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled_exception path=%s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "detail": "Unexpected server error",
            "path": request.url.path,
        },
    )

# Wire up core application routing matrices
app.include_router(users.router)
app.include_router(queues.router)
app.include_router(jobs.router)
app.include_router(dashboard.router)

app.mount("/dashboard", StaticFiles(directory="app/dashboard"), name="dashboard_static")


@app.get("/dashboard")
def dashboard_index():
    return FileResponse("app/dashboard/index.html")


@app.get("/api/v1/metrics")
def metrics(current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        rows = db.execute(text("SELECT status, COUNT(*) AS count FROM jobs GROUP BY status")).all()
        counts = {str(status).upper(): int(count) for status, count in rows if status is not None}
        return {
            "job_status_counts": counts,
            "total_jobs": sum(counts.values()),
        }
    finally:
        db.close()


@app.get("/")
def health_check():
    return {"status": "operational", "engine": "FastAPI Monolith"}
