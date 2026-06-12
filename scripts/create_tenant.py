"""Create a tenant and issue it an API key.

The raw key is printed once and never stored — only its hash is persisted.

Usage:
    uv run python scripts/create_tenant.py "Acme Inc"
"""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

# Allow running as a plain script (`python scripts/create_tenant.py`) by putting
# the project root on the path so `src` is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api.security import generate_api_key, hash_api_key  # noqa: E402
from src.storage.database import AsyncSessionFactory, engine  # noqa: E402
from src.storage.models import ApiKey, Tenant  # noqa: E402


async def main(name: str) -> None:
    raw_key = generate_api_key()
    now = datetime.now(UTC)
    tenant_id = uuid4().hex
    async with AsyncSessionFactory() as session:
        session.add(Tenant(id=tenant_id, name=name, is_active=True, created_at=now))
        # Flush so the tenant row exists before the key's FK references it.
        await session.flush()
        session.add(
            ApiKey(
                id=uuid4().hex,
                tenant_id=tenant_id,
                key_hash=hash_api_key(raw_key),
                created_at=now,
            )
        )
        await session.commit()
    await engine.dispose()

    print(f"tenant_id: {tenant_id}")
    print(f"name:      {name}")
    print(f"api_key:   {raw_key}")
    print("Store the api_key now — it cannot be recovered.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: uv run python scripts/create_tenant.py <tenant-name>")
        raise SystemExit(2)
    asyncio.run(main(sys.argv[1]))
