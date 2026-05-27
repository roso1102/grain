from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.logger import logger
from app.core.config import settings
from app.api import health, ingest, search, graph, facets, auth, dashboard
from app.db.migrate import run_pending as run_migrations

app = FastAPI(
    title="Grain - Personal Knowledge Operating System",
    description="An AI-powered PKOS for capturing, structuring, connecting, and recall of knowledge.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://higrain.vercel.app",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(search.router)
app.include_router(graph.router)
app.include_router(facets.router)
app.include_router(auth.router)
app.include_router(dashboard.router)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting up Grain PKOS...")
    logger.info(f"Loaded config. Host: {settings.HOST}:{settings.PORT}")
    await run_migrations()

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Grain PKOS...")

@app.get("/")
async def root():
    return {
        "message": "Welcome to Grain PKOS. Capture first, let AI organize.",
        "docs_url": "/docs"
    }
