"""Raw SQL used by the Postgres connector's introspection layer.

Uses `pg_catalog` directly (not just `information_schema`) because we need
`reltuples`/`pg_total_relation_size` for stats and `obj_description`/
`col_description` for source comments, none of which the SQL-standard
`information_schema` view exposes.
"""

DEFAULT_EXCLUDED_SCHEMAS = ("pg_catalog", "information_schema")

LIST_SCHEMAS = """
    SELECT schema_name
    FROM information_schema.schemata
    WHERE schema_name NOT IN %(excluded)s
      AND schema_name NOT LIKE 'pg\\_toast%%'
      AND schema_name NOT LIKE 'pg\\_temp%%'
    ORDER BY schema_name
"""

# c.relkind: r=table, p=partitioned table, f=foreign table, v=view, m=materialized view
LIST_TABLES = """
    SELECT
        n.nspname AS schema_name,
        c.relname AS table_name,
        CASE c.relkind
            WHEN 'r' THEN 'table'
            WHEN 'p' THEN 'table'
            WHEN 'f' THEN 'table'
            WHEN 'v' THEN 'view'
            WHEN 'm' THEN 'materialized_view'
        END AS object_type,
        CASE WHEN c.relkind IN ('r', 'p', 'm') THEN c.reltuples::bigint ELSE NULL END AS row_count_estimate,
        CASE WHEN c.relkind IN ('r', 'p', 'm') THEN pg_total_relation_size(c.oid) ELSE NULL END AS size_bytes_estimate,
        obj_description(c.oid, 'pg_class') AS description,
        pg_get_userbyid(c.relowner) AS db_owner_role,
        c.oid AS table_oid
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r', 'p', 'f', 'v', 'm')
      AND n.nspname = %(schema)s
    ORDER BY c.relname
"""

LIST_COLUMNS = """
    SELECT
        a.attname AS column_name,
        a.attnum AS ordinal_position,
        format_type(a.atttypid, a.atttypmod) AS native_data_type,
        NOT a.attnotnull AS is_nullable,
        col_description(a.attrelid, a.attnum) AS description
    FROM pg_attribute a
    WHERE a.attrelid = %(table_oid)s
      AND a.attnum > 0
      AND NOT a.attisdropped
    ORDER BY a.attnum
"""

LIST_CONSTRAINTS = """
    SELECT
        con.conname,
        con.contype,
        con.conkey,
        con.confrelid,
        con.confkey,
        fn.nspname AS ref_schema_name,
        fc.relname AS ref_table_name
    FROM pg_constraint con
    LEFT JOIN pg_class fc ON fc.oid = con.confrelid
    LEFT JOIN pg_namespace fn ON fn.oid = fc.relnamespace
    WHERE con.conrelid = %(table_oid)s
      AND con.contype IN ('p', 'f')
"""

# attnum -> attname lookup for a given relation (used to resolve conkey /
# confkey int arrays to column names for FK reference resolution).
LIST_ATTNAME_BY_NUM = """
    SELECT attnum, attname
    FROM pg_attribute
    WHERE attrelid = %(table_oid)s AND attnum > 0 AND NOT attisdropped
"""
