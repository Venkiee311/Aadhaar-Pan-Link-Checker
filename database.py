import os
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# On Railway, volumes are mounted at a path like '/data'. We default to a local 'data' folder.
DATA_ROOT = Path(os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "data"))
DATA_ROOT.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite+aiosqlite:///{DATA_ROOT / 'aadhar_processing.db'}"

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        