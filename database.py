import os
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Use the RENDER_DISK_MOUNT_PATH if available, otherwise default to a local 'data' directory
DATA_ROOT = Path(os.getenv("RENDER_DISK_MOUNT_PATH", "data"))
DATA_ROOT.mkdir(exist_ok=True) # Ensure the data directory exists

DATABASE_URL = f"sqlite+aiosqlite:///{DATA_ROOT / 'aadhar_processing.db'}"

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)