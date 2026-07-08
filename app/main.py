from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.view import router as view_router
from app.api.artifacts import router as artifacts_router
from app.api.projects import router as projects_router
from app.api.questions import router as questions_router
from app.api.settings import router as settings_router
from app.api.workflow import router as workflow_router
from app.core.config import settings
from app.db.repositories import fail_stale_running_projects
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    fail_stale_running_projects()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(projects_router)
app.include_router(view_router)
app.include_router(questions_router)
app.include_router(artifacts_router)
app.include_router(workflow_router)
app.include_router(settings_router)

static_dir = Path(__file__).parent / "static"
app.mount("/ui", StaticFiles(directory=static_dir, html=True), name="ui")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}
