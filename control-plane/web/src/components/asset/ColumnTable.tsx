import type { Column } from '../../types/catalog'

/** Standard column table shared by Table detail and schema-inferred Dataset detail (design.md §3 — "Table and Dataset render as peers"). */
export function ColumnTable({ columns }: { columns: Column[] }) {
  return (
    <table className="column-table">
      <thead>
        <tr>
          <th>Column</th>
          <th>Type</th>
          <th>Nullable</th>
          <th>Key</th>
          <th>Description</th>
        </tr>
      </thead>
      <tbody>
        {columns.map((c) => (
          <tr key={c.name}>
            <td>{c.name}</td>
            <td>{c.native_data_type}</td>
            <td>{c.is_nullable ? 'yes' : 'no'}</td>
            <td>
              {c.is_primary_key && <span className="key-badge key-badge--pk">PK</span>}
              {c.is_foreign_key && <span className="key-badge key-badge--fk">FK→{c.foreign_key_ref ?? '?'}</span>}
            </td>
            <td>{c.description ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
