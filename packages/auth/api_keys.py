import hashlib
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import ApiKey

API_KEY_PREFIX = "mmrag_"


def generate_api_key() -> tuple[str, str]:
    """Returns (plaintext_key, key_hash). The plaintext is returned to the caller exactly
    once (at creation); only key_hash is ever persisted."""
    plaintext_key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return plaintext_key, hash_api_key(plaintext_key)


def hash_api_key(plaintext_key: str) -> str:
    return hashlib.sha256(plaintext_key.encode()).hexdigest()


def is_api_key(bearer_value: str) -> bool:
    return bearer_value.startswith(API_KEY_PREFIX)


async def resolve_active_api_key(session: AsyncSession, plaintext_key: str) -> ApiKey | None:
    """Looks up an API key by its hash and returns it only if not revoked. api_keys carries
    tenant_id directly and isn't RLS-protected differently from other lookups here — this
    query runs before the GUC is set, same bootstrap-ordering reasoning as
    packages.auth.context's tenant/workspace role resolution."""
    key_hash = hash_api_key(plaintext_key)
    api_key = await session.scalar(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
    )
    return api_key
