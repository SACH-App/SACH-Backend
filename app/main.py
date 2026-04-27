from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.redis import redis_manager
from app.api.v1.endpoints import verification, admin, user, mobile

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Connect to Upstash Redis
    await redis_manager.connect()
    yield
    # Shutdown: Close Redis connection
    await redis_manager.close()

app = FastAPI(
    title="SACH Unified Backend",
    description="Backend API for SACH FIR Management System (React Admin, React User, Flutter Mobile)",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS for the three frontends
origins = [
    "http://localhost:3000",      # React User Website (Development)
    "http://localhost:3001",      # React Admin Website (Development)
    "http://localhost:8080",      # Flutter Web
    "capacitor://localhost",      # Flutter Mobile
    "ionic://localhost",
    # Add production URLs here
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For development. Restrict to `origins` in production.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(verification.router, prefix="/api/v1/verification", tags=["Verification"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(user.router, prefix="/api/v1/user", tags=["User"])
app.include_router(mobile.router, prefix="/api/v1/mobile", tags=["Mobile"])

@app.get("/", tags=["Health"])
async def root():
    return {"message": "Welcome to SACH Unified Backend API"}
