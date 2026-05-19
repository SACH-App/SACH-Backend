import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def migrate():
    print("Connecting to database...")
    async with AsyncSessionLocal() as db:
        print("Executing ALTER TABLE statements...")
        await db.execute(text("ALTER TABLE firs ADD COLUMN IF NOT EXISTS latitude FLOAT;"))
        await db.execute(text("ALTER TABLE firs ADD COLUMN IF NOT EXISTS longitude FLOAT;"))
        await db.commit()
        print("Database schema successfully updated with latitude/longitude fields.")

if __name__ == "__main__":
    asyncio.run(migrate())
