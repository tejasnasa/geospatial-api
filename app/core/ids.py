"""Short random ID generation for public file identifiers."""

from __future__ import annotations

import secrets

from app.core.config import get_settings


def generate_file_id() -> str:
    """Return a random public ID for a stored file."""

    settings = get_settings()
    # secrets.choice over our alphabet keeps it short and URL-safe.
    return "".join(secrets.choice(settings.id_alphabet) for _ in range(settings.id_length))
