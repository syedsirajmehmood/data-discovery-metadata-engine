"""Apply the baseline schema locally.

Two equivalent ways to bootstrap a dev database, kept in sync by hand
(``models.py`` is the source of truth; ``migrations/001_init.sql`` is the
plain-SQL mirror of it for anyone who wants to `psql -f` it directly, e.g. in
CI or a fresh docker-compose Postgres):

    python -m storage.relational.migrate

Set connection info via ``POSTGRES_DSN`` or the ``POSTGRES_*`` env vars
documented in ``db.py``.
"""

from __future__ import annotations

from storage.relational.db import make_engine
from storage.relational.models import Base


def main() -> None:
    engine = make_engine()
    Base.metadata.create_all(engine)
    print("storage.relational: schema created (or already present).")


if __name__ == "__main__":
    main()
