import os
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool

# Use the RENDER_DISK_MOUNT_PATH if available, otherwise default to a local 'data' directory
DATA_ROOT = Path(os.getenv("RENDER_DISK_MOUNT_PATH", "data"))
DATA_ROOT.mkdir(exist_ok=True) # Ensure the data directory exists

DATABASE_URL = f"sqlite+aiosqlite:///{DATA_ROOT / 'aadhar_processing.db'}"

# Optimize engine configuration for SQLite
engine = create_async_engine(
    DATABASE_URL, 
    echo=False,
    poolclass=StaticPool,  # Use static pool for SQLite
    pool_pre_ping=True,  # Verify connections before use
    pool_recycle=3600,  # Recycle connections every hour
    connect_args={
        "timeout": 30,  # Connection timeout
        "check_same_thread": False,  # Allow async operations
    }
)

SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)