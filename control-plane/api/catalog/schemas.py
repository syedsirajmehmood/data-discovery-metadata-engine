"""Pydantic response models for the catalog read API.

This module IS the contract FE3's UI builds against — field names/shapes
here are what ships over the wire. Kept deliberately permissive on input
(`extra="ignore"` on models fed from ORM rows / OpenSearch docs) so a store
adding an internal-only column never breaks the API without an explicit
schema change here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class SearchResultItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    urn: str
    entity_type: str
    source_type: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    owner: Optional[str] = None
    fully_qualified_name: Optional[str] = None
    last_scraped_at: Optional[str] = None
    score: Optional[float] = None


class SearchResponse(BaseModel):
    total: int
    results: list[SearchResultItem]


class ColumnDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    urn: str
    table_urn: str
    name: str
    ordinal_position: int
    native_data_type: str
    normalized_data_type: str
    is_nullable: bool
    is_primary_key: bool
    is_foreign_key: bool
    foreign_key_ref: Optional[dict] = None
    description: Optional[str] = None
    description_source: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    is_deleted: bool = False
    last_scraped_at: Optional[datetime] = None


class TableDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    urn: str
    fully_qualified_name: str
    source_type: str
    database_name: str
    schema_name: str
    table_name: str
    object_type: str
    description: Optional[str] = None
    description_source: Optional[str] = None
    owner: Optional[str] = None
    owner_source: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    row_count_estimate: Optional[int] = None
    size_bytes_estimate: Optional[int] = None
    source_connection_id: str
    data_plane_id: Any
    first_seen_at: Optional[datetime] = None
    last_scraped_at: Optional[datetime] = None
    is_deleted: bool = False


class TableDetailResponse(BaseModel):
    table: TableDetail
    columns: list[ColumnDetail]


class LineageNode(BaseModel):
    urn: str
    entity_type: str
    hops: int


class LineageResponse(BaseModel):
    urn: str
    upstream: list[LineageNode]
    downstream: list[LineageNode]


class SourceConnectionStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_connection_id: str
    last_run_status: Optional[str] = None
    last_run_started_at: Optional[datetime] = None
    last_run_completed_at: Optional[datetime] = None
    entities_seen_count: int = 0
    entities_created_count: int = 0
    entities_tombstoned_count: int = 0
    error_summary: Optional[str] = None


class SourceStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_plane_id: str
    data_plane_name: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    source_connections: list[SourceConnectionStatus] = Field(default_factory=list)


class SourcesStatusResponse(BaseModel):
    sources: list[SourceStatus]
