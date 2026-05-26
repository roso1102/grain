import asyncio
from fastapi import FastAPI
from app.core.logger import logger
from app.core.config import settings
from app.api import health, ingest, search, graph, facets
from app.services.notion_sync import poll_notion_updates

app = FastAPI(
    title="Grain - Personal Knowledge Operating System",
    description="An AI-powered PKOS for capturing, structuring, connecting, and recall of knowledge.",
    version="1.0.0"
)

# Include API Routers
app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(search.router)
app.include_router(graph.router)
app.include_router(facets.router)

async def notion_polling_loop():
    logger.info("Notion two-way sync polling loop initiated.")
    while True:
        try:
            await poll_notion_updates()
        except Exception as e:
            logger.error(f"Error in Notion polling loop: {e}", exc_info=True)
        # Sleep for 5 minutes (300 seconds)
        await asyncio.sleep(300)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting up Grain PKOS...")
    logger.info(f"Loaded config. Host: {settings.HOST}:{settings.PORT}")
    # Start the Notion two-way sync background poller
    asyncio.create_task(notion_polling_loop())

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Grain PKOS...")

@app.get("/")
async def root():
    return {
        "message": "Welcome to Grain PKOS. Capture first, let AI organize.",
        "docs_url": "/docs"
    }
