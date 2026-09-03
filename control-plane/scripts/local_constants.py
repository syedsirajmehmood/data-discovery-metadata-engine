"""Shared constants for the local-run scripts in this directory. Not part
of any engineer's owned scope — added by the orchestrator to make `npm
run dev` / `pytest` -level local testing extend into an actual running
system. See RUNBOOK.md at the repo root for the full walkthrough.

One fixed tenant and one API key, reused for BOTH the data-plane push path
(registered in FE1's in-memory registry by run_ingest_local.py) and the
catalog-read path (a real Postgres api_keys row created by
bootstrap_local.py) — simpler than juggling two keys for a local demo.
Production would never do this (the two auth paths are intentionally
separate systems - see status.md's "still not done" list).
"""
import uuid

LOCAL_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
LOCAL_API_KEY = "local-dev-key"
LOCAL_DATA_PLANE_ID = "dp-local-1"
