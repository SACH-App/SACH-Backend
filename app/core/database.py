"""
Database configuration and session management.
Initializes the async SQLAlchemy engine and provides the get_db dependency.
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from app.core.config import settings

# Create async engine for PostgreSQL
engine = create_async_engine(
    settings.DATABASE_URL, 
    echo=settings.DEBUG,
    pool_pre_ping=True,  # Verify connections before using them
    connect_args={"statement_cache_size": 0}
)

# Create session factory bound to engine
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession
)

# Declarative base class for models
Base = declarative_base()

async def get_db():
    """Dependency to provide a database session per request."""
    async with AsyncSessionLocal() as session:
        yield session
