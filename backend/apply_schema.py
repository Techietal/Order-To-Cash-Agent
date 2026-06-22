import asyncio
from database.postgres import init_schema

async def main():
    await init_schema()
    print("Schema applied successfully!")

if __name__ == "__main__":
    asyncio.run(main())
