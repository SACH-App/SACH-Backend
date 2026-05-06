from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.redis import redis_manager
from app.core.logging_config import setup_logging, get_logger
from app.core.exceptions import (
    validation_exception_handler,
    sqlalchemy_exception_handler,
    generic_exception_handler,
)
from app.api.v1.endpoints import verification, admin, user, mobile

# Initialize logging
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting SACH Backend...")
    await redis_manager.connect()
    logger.info("Redis connected")
    yield
    # Shutdown
    await redis_manager.close()
    logger.info("SACH Backend shut down")


app = FastAPI(
    title="SACH Unified Backend",
    description="Backend API for SACH FIR Management System (React Admin, React User, Flutter Mobile)",
    version="2.0.0",
    lifespan=lifespan,
)

# ── Global Exception Handlers ──
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# ── CORS ──
origins = [
    "http://localhost:3000",      # React User Website (Development)
    "http://localhost:3001",      # React Admin Website (Development)
    "http://localhost:5173",      # Vite Dev Server
    "http://localhost:8080",      # Flutter Web
    "capacitor://localhost",      # Flutter Mobile (Capacitor)
    "ionic://localhost",
    # Add production URLs here
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development. Restrict to `origins` in production.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──
app.include_router(verification.router, prefix="/api/v1/verification", tags=["Verification"])
app.include_router(user.router,         prefix="/api/v1/user",         tags=["User / Citizen"])
app.include_router(admin.router,        prefix="/api/v1/admin",        tags=["Admin / Officer"])
app.include_router(mobile.router,       prefix="/api/v1/mobile",       tags=["Mobile"])


@app.get("/", tags=["Health"])
async def root():
    return {
        "message": "Welcome to SACH Unified Backend API",
        "version": "2.0.0",
        "docs": "/docs",
    }
