from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.admin import router as admin_router
from app.api.arguments import router as arguments_router
from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.debates import router as debates_router
from app.api.evidence import router as evidence_router
from app.api.export import router as export_router
from app.api.knowledge import router as knowledge_router
from app.api.collaboration import router as collaboration_router
from app.api.verification import router as verification_router
from app.api.corrections import router as corrections_router
from app.api.library import router as library_router
from app.api.fable import router as fable_router
from app.core.config import settings
from app.core.database import Base, database_ready, engine

if settings.auto_create_schema:
    Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.app_name,
    description="Evidence-centered debate platform API",
    version="1.0.0-rc2",
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health/live")
def liveness():
    return {"status": "ok", "service": settings.app_name}


@app.get("/health/ready")
def readiness():
    ready = database_ready()
    return {"status": "ready" if ready else "not_ready", "database": ready}


@app.get("/health")
def health():
    return liveness()


app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(dashboard_router)
app.include_router(debates_router)
app.include_router(arguments_router)
app.include_router(evidence_router)
app.include_router(export_router)
app.include_router(knowledge_router)
app.include_router(collaboration_router)
app.include_router(verification_router)
app.include_router(corrections_router)
app.include_router(library_router)
app.include_router(fable_router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", include_in_schema=False)
def web_app():
    return FileResponse("app/static/index.html")
