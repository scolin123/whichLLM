from contextlib import asynccontextmanager
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.routers import keys, arena, chat

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("startup", env=settings.app_env)

    # Verify Redis is reachable
    from app.services.cache import get_redis
    redis = await get_redis()
    await redis.ping()
    await redis.aclose()

    # Verify DB is reachable
    from app.db.session import engine
    async with engine.connect() as conn:
        await conn.execute(__import__("sqlalchemy").text("SELECT 1"))

    logger.info("startup_complete")
    yield

    await engine.dispose()
    logger.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="LLM Arena API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(keys.router)
    app.include_router(arena.router)
    app.include_router(chat.router)
    return app


app = create_app()
