"""Memory tool — persistent, scope-aware memory storage with embeddings and search.

The mait-code memory store is a SQLite-backed log of observations, decisions,
and other facts that survive across sessions. Entries are scoped by project
and branch, scored by a recency/importance composite, and queryable via
keyword, vector, or hybrid search.

This package exposes the CLI entry point (``main``) plus the library surface
that contributors call when extending the tool: connection helpers, embedding
providers, search functions, scoring helpers, entity-graph operations, the
write/dedup path, and the reflection pipeline.
"""

from mait_code.tools.memory.cli import main
from mait_code.tools.memory.db import (
    connection,
    get_connection,
    get_data_dir,
    get_db_path,
)
from mait_code.tools.memory.embeddings import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    BedrockProvider,
    EmbeddingProvider,
    LocalProvider,
    check_dimension_match,
    embed_text,
    embed_texts,
    get_provider,
    is_available,
    serialize_f32,
)
from mait_code.tools.memory.entities import (
    find_entity_by_name,
    get_ego_graph,
    get_entity_relationships,
    list_graph_entities,
    merge_entities,
    search_entities,
    upsert_entity,
    upsert_relationship,
)
from mait_code.tools.memory.migrate import ensure_schema
from mait_code.tools.memory.native import (
    list_native_memories,
    native_projects_dir,
    resolve_slug,
)
from mait_code.tools.memory.observations import (
    daily_batches,
    list_observations,
    observation_projects,
)
from mait_code.tools.memory.reflect import (
    count_unreflected,
    get_last_reflected_at,
    reflect,
)
from mait_code.tools.memory.scoring import (
    composite_score,
    importance_score,
    recency_score,
    scope_boost,
)
from mait_code.tools.memory.search import (
    delete_entry,
    hybrid_search,
    list_entries,
    list_projects,
    search_entries,
    vector_search_entries,
)
from mait_code.tools.memory.stats import MemoryStats, collect_stats
from mait_code.tools.memory.writer import (
    find_duplicate,
    merge_memories,
    retire_memory,
    store_memory,
    supersede_memory,
)

__all__ = [
    # CLI
    "main",
    # Storage
    "connection",
    "ensure_schema",
    "get_connection",
    "get_data_dir",
    "get_db_path",
    # Embeddings
    "BedrockProvider",
    "EMBEDDING_DIM",
    "EMBEDDING_MODEL",
    "EmbeddingProvider",
    "LocalProvider",
    "check_dimension_match",
    "embed_text",
    "embed_texts",
    "get_provider",
    "is_available",
    "serialize_f32",
    # Search
    "delete_entry",
    "hybrid_search",
    "list_entries",
    "list_projects",
    "search_entries",
    "vector_search_entries",
    # Scoring
    "composite_score",
    "importance_score",
    "recency_score",
    "scope_boost",
    # Entities
    "find_entity_by_name",
    "get_ego_graph",
    "get_entity_relationships",
    "list_graph_entities",
    "merge_entities",
    "search_entities",
    "upsert_entity",
    "upsert_relationship",
    # Writer
    "find_duplicate",
    "merge_memories",
    "retire_memory",
    "store_memory",
    "supersede_memory",
    # Stats
    "MemoryStats",
    "collect_stats",
    # Reflection
    "count_unreflected",
    "get_last_reflected_at",
    "reflect",
    # Observations
    "daily_batches",
    "list_observations",
    "observation_projects",
    # Native auto memory
    "list_native_memories",
    "native_projects_dir",
    "resolve_slug",
]
