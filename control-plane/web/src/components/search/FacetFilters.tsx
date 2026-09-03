import type { SearchFacets } from '../../types/catalog'

export interface FacetSelection {
  entityTypes: string[]
  sourceConnectionIds: string[]
  tags: string[]
}

/**
 * Facet filters: entity type, source connection, tags (design.md §2).
 * No owner facet — explicitly not AC-1-required.
 */
export function FacetFilters({
  facets,
  selection,
  onChange,
}: {
  facets: SearchFacets
  selection: FacetSelection
  onChange: (next: FacetSelection) => void
}) {
  function toggle(list: string[], value: string): string[] {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
  }

  return (
    <aside className="facet-filters" aria-label="Filters">
      <h2>Filters</h2>

      <fieldset>
        <legend>Entity type</legend>
        {facets.entity_type.map((opt) => (
          <label key={opt.value}>
            <input
              type="checkbox"
              checked={selection.entityTypes.includes(opt.value)}
              onChange={() => onChange({ ...selection, entityTypes: toggle(selection.entityTypes, opt.value) })}
            />
            {opt.value === 'table' ? 'Table' : 'Dataset'} ({opt.count})
          </label>
        ))}
      </fieldset>

      <fieldset>
        <legend>Source connection</legend>
        {facets.source_connection.map((opt) => (
          <label key={opt.value.id}>
            <input
              type="checkbox"
              checked={selection.sourceConnectionIds.includes(opt.value.id)}
              onChange={() =>
                onChange({ ...selection, sourceConnectionIds: toggle(selection.sourceConnectionIds, opt.value.id) })
              }
            />
            {opt.value.name} ({opt.count})
          </label>
        ))}
      </fieldset>

      {facets.tags.length > 0 && (
        <fieldset>
          <legend>Tags</legend>
          {facets.tags.map((opt) => (
            <label key={opt.value}>
              <input
                type="checkbox"
                checked={selection.tags.includes(opt.value)}
                onChange={() => onChange({ ...selection, tags: toggle(selection.tags, opt.value) })}
              />
              {opt.value} ({opt.count})
            </label>
          ))}
        </fieldset>
      )}
    </aside>
  )
}
