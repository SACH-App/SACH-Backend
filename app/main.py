from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from starlette.responses import HTMLResponse
from sqlalchemy.exc import SQLAlchemyError

from app.core.redis import redis_manager, get_redis
from app.core.logging_config import setup_logging, get_logger
from app.core.exceptions import (
    validation_exception_handler,
    sqlalchemy_exception_handler,
    generic_exception_handler,
)
from app.api.v1.endpoints import verification, admin, user, mobile
from app.services.nadra_service import init_client, close_client

# Initialize logging
setup_logging()
logger = get_logger(__name__)

# ── Dark mode CSS for Swagger UI ──
SWAGGER_DARK_CSS = """
body { background-color: #1a1a2e !important; }
.swagger-ui { background-color: #1a1a2e !important; }
.swagger-ui .topbar { background-color: #16213e !important; }
.swagger-ui .info .title, .swagger-ui .info .title small { color: #e2e8f0 !important; }
.swagger-ui .info p, .swagger-ui .info li { color: #a0aec0 !important; }
.swagger-ui .scheme-container { background-color: #16213e !important; box-shadow: none !important; }
.swagger-ui .opblock-tag { color: #e2e8f0 !important; border-bottom: 1px solid #2d3748 !important; }
.swagger-ui .opblock-tag:hover { background: #16213e !important; }
.swagger-ui .opblock { border-color: #2d3748 !important; background: #16213e !important; }
.swagger-ui .opblock .opblock-summary { border-color: #2d3748 !important; }
.swagger-ui .opblock .opblock-summary-description { color: #a0aec0 !important; }
.swagger-ui .opblock .opblock-summary-path { color: #e2e8f0 !important; }
.swagger-ui .opblock .opblock-section-header { background: #1a1a2e !important; }
.swagger-ui .opblock .opblock-section-header h4 { color: #e2e8f0 !important; }
.swagger-ui .opblock-body pre { background: #0f0f23 !important; color: #63b3ed !important; }
.swagger-ui .opblock.opblock-get { background: rgba(97,175,254,.08) !important; border-color: #3182ce !important; }
.swagger-ui .opblock.opblock-post { background: rgba(73,204,144,.08) !important; border-color: #38a169 !important; }
.swagger-ui .opblock.opblock-put { background: rgba(252,161,48,.08) !important; border-color: #d69e2e !important; }
.swagger-ui .opblock.opblock-delete { background: rgba(249,62,62,.08) !important; border-color: #e53e3e !important; }
.swagger-ui table thead tr th, .swagger-ui table thead tr td { color: #e2e8f0 !important; border-bottom: 1px solid #2d3748 !important; }
.swagger-ui table tbody tr td { color: #a0aec0 !important; border-bottom: 1px solid #2d3748 !important; }
.swagger-ui .parameter__name { color: #e2e8f0 !important; }
.swagger-ui .parameter__type { color: #63b3ed !important; }
.swagger-ui .response-col_status { color: #e2e8f0 !important; }
.swagger-ui .response-col_description { color: #a0aec0 !important; }
.swagger-ui .responses-inner { background: #1a1a2e !important; }
.swagger-ui .model-box { background: #16213e !important; }
.swagger-ui .model { color: #e2e8f0 !important; }
.swagger-ui .model-title { color: #e2e8f0 !important; }
.swagger-ui section.models { border: 1px solid #2d3748 !important; }
.swagger-ui section.models h4 { color: #e2e8f0 !important; }
.swagger-ui .btn { color: #e2e8f0 !important; border-color: #4a5568 !important; }
.swagger-ui .btn:hover { background: #2d3748 !important; }
.swagger-ui select { background: #16213e !important; color: #e2e8f0 !important; border-color: #4a5568 !important; }
.swagger-ui input[type=text] { background: #16213e !important; color: #e2e8f0 !important; border-color: #4a5568 !important; }
.swagger-ui textarea { background: #16213e !important; color: #e2e8f0 !important; border-color: #4a5568 !important; }
.swagger-ui .markdown p, .swagger-ui .markdown li { color: #a0aec0 !important; }
.swagger-ui .loading-container .loading::after { color: #e2e8f0 !important; }
.swagger-ui .response-control-media-type--accept-controller select { background: #16213e !important; }
.swagger-ui .copy-to-clipboard { background: #2d3748 !important; }
.swagger-ui .download-contents { background: #2d3748 !important; color: #e2e8f0 !important; }
.swagger-ui .opblock-description-wrapper p { color: #a0aec0 !important; }
.swagger-ui .tab li { color: #a0aec0 !important; }
.swagger-ui .tab li.active { color: #e2e8f0 !important; }
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting SACH Backend...")
    await redis_manager.connect()
    logger.info("Redis connected")
    await init_client()
    logger.info("NADRA HTTP client ready")
    yield
    # Shutdown
    await close_client()
    await redis_manager.close()
    logger.info("SACH Backend shut down")


app = FastAPI(
    title="SACH Unified Backend",
    description="Backend API for SACH FIR Management System (React Admin, React User, Flutter Mobile)",
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None,    # Disable default so we serve our dark version
    redoc_url=None,   # Disable default ReDoc
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


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui():
    """Serve Swagger UI with dark mode."""
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>SACH API - Docs</title>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
        <style>{SWAGGER_DARK_CSS}</style>
    </head>
    <body>
        <div id="swagger-ui"></div>
        <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
        <script>
        SwaggerUIBundle({{
            url: '/openapi.json',
            dom_id: '#swagger-ui',
            presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
            layout: "BaseLayout",
            deepLinking: true,
        }})
        </script>
    </body>
    </html>
    """)


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Deep health check — verifies that Redis is reachable and warm.
    Use this before critical operations to avoid cold-start issues.
    """
    redis_status = "disconnected"
    redis_latency_ms = None

    try:
        redis_client = get_redis()
        if redis_client:
            import time
            start = time.monotonic()
            pong = await redis_client.ping()
            elapsed = (time.monotonic() - start) * 1000  # ms
            if pong:
                redis_status = "connected"
                redis_latency_ms = round(elapsed, 2)
    except Exception as e:
        redis_status = f"error: {str(e)}"

    healthy = redis_status == "connected"

    return {
        "status": "healthy" if healthy else "degraded",
        "services": {
            "redis": {
                "status": redis_status,
                "latency_ms": redis_latency_ms,
            }
        }
    }
