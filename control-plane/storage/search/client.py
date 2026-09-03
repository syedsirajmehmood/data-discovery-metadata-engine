"""OpenSearch client construction from environment variables.

- ``OPENSEARCH_HOST`` (default ``localhost``), ``OPENSEARCH_PORT`` (default ``9200``)
- ``OPENSEARCH_USE_SSL`` (default ``false``)
- ``OPENSEARCH_USER`` / ``OPENSEARCH_PASSWORD`` (optional basic auth)
"""

from __future__ import annotations

import os

from opensearchpy import OpenSearch


def build_client() -> OpenSearch:
    host = os.environ.get("OPENSEARCH_HOST", "localhost")
    port = int(os.environ.get("OPENSEARCH_PORT", "9200"))
    use_ssl = os.environ.get("OPENSEARCH_USE_SSL", "false").lower() == "true"
    user = os.environ.get("OPENSEARCH_USER")
    password = os.environ.get("OPENSEARCH_PASSWORD")
    http_auth = (user, password) if user and password else None
    return OpenSearch(
        hosts=[{"host": host, "port": port}],
        http_auth=http_auth,
        use_ssl=use_ssl,
        verify_certs=False,
    )
