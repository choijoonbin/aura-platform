"""
Aura-Platform Main Entry Point

FastAPI 애플리케이션의 진입점입니다.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from api.middleware import setup_middlewares
from core.memory.redis_store import get_redis_store, cleanup_redis

# 로깅 설정
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    애플리케이션 라이프사이클 관리
    
    시작 시: Redis 연결 초기화
    종료 시: Redis 연결 정리
    """
    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment: {settings.app_env}")
    
    # Redis 연결 초기화
    try:
        redis_store = await get_redis_store()
        logger.info("Redis connection established")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down application")
    await cleanup_redis()


# FastAPI 애플리케이션 초기화
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Agentic AI Platform for DWP - Modular SDLC Automation",
    debug=settings.debug,
    lifespan=lifespan,
)

# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 커스텀 미들웨어 설정
setup_middlewares(app)

# API 라우터 등록
from api.routes.agents import router as agents_router
from api.routes.agents_enhanced import router as agents_enhanced_router

app.include_router(agents_router)
app.include_router(agents_enhanced_router)  # 프론트엔드 명세 v1.0


@app.get("/")
async def root() -> dict[str, str]:
    """
    루트 엔드포인트
    
    Returns:
        환영 메시지
    """
    return {
        "message": f"Welcome to {settings.app_name}!",
        "version": settings.app_version,
        "status": "operational",
    }


@app.get("/health")
async def health_check() -> dict[str, str]:
    """
    헬스체크 엔드포인트
    
    Returns:
        서버 상태
    """
    return {
        "status": "healthy",
        "environment": settings.app_env,
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
        log_level=settings.log_level.lower(),
    )
