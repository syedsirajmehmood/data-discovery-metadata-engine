"""One-time local bootstrap for running the real stack (see RUNBOOK.md):

    PYTHONPATH="$(pwd)" .venv/bin/python scripts/bootstrap_local.py

Requires `docker compose -f ../infra/docker-compose.yml up -d` already
running, and POSTGRES_PORT=5433 set in the environment (the compose file
publishes Postgres on a non-default host port — see infra/docker-compose.yml).

Does four things:
  1. Creates the Postgres schema (equivalent to storage.relational.migrate).
  2. Inserts a fixed local tenant + a catalog-read API key row, so the
     catalog API (api/catalog/) can authenticate a request.
  3. Ensures the OpenSearch index exists (SearchIndex.ensure_index()).
  4. Ensures the ClickHouse tables exist (AnalyticsStore.ensure_schema()).

Safe to re-run — every step is idempotent.
"""
from __future__ import annotations

import hashlib

from sqlalchemy import select

from scripts.local_constants import LOCAL_API_KEY, LOCAL_TENANT_ID
from storage.analytics.store import AnalyticsStore
from storage.relational.db import make_engine, make_session_factory
from storage.relational.models import ApiKey, Base, Tenant
from storage.search.store import SearchIndex


def main() -> None:
    engine = make_engine()
    Base.metadata.create_all(engine)
    print("postgres: schema created (or already present)")

    session_factory = make_session_factory(engine)
    with session_factory() as session:
        tenant = session.get(Tenant, LOCAL_TENANT_ID)
        if tenant is None:
            session.add(Tenant(id=LOCAL_TENANT_ID, name="local-dev"))
            session.flush()
            print(f"postgres: created tenant {LOCAL_TENANT_ID}")
        else:
            print(f"postgres: tenant {LOCAL_TENANT_ID} already exists")

        key_hash = hashlib.sha256(LOCAL_API_KEY.encode("utf-8")).hexdigest()
        existing_key = session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash)).scalar_one_or_none()
        if existing_key is None:
            session.add(
                ApiKey(
                    tenant_id=LOCAL_TENANT_ID,
                    data_plane_id=None,  # read key, not a data-plane push key
                    key_hash=key_hash,
                    label="local-dev catalog-read key",
                )
            )
            print("postgres: created catalog-read API key row")
        else:
            print("postgres: catalog-read API key row already exists")
        session.commit()

    SearchIndex().ensure_index()
    print("opensearch: index ensured")

    AnalyticsStore().ensure_schema()
    print("clickhouse: schema ensured")

    print()
    print(f"LOCAL_TENANT_ID = {LOCAL_TENANT_ID}")
    print(f"LOCAL_API_KEY   = {LOCAL_API_KEY!r}  (Authorization: Bearer {LOCAL_API_KEY})")


if __name__ == "__main__":
    main()
