import type { DatasetEntity } from '../../types/catalog'
import { formatBytesEstimate, formatCountEstimate } from '../../lib/format'

/**
 * AC-2a required state: a Dataset whose connector could not infer a
 * schema. Must render visibly differently from an empty column table —
 * never a bare <table> with a header row and nothing under it.
 */
export function NoSchemaInferredBlock({ dataset }: { dataset: DatasetEntity }) {
  return (
    <div className="no-schema-block">
      <p className="no-schema-block__headline">No schema could be inferred for this dataset.</p>
      <p className="muted">
        ({dataset.file_format ?? 'unknown'} file format — showing file-level metadata)
      </p>

      <dl className="no-schema-block__facts">
        <div>
          <dt>Format</dt>
          <dd>{dataset.file_format ?? 'unknown'}</dd>
        </div>
        <div>
          <dt>Object count</dt>
          <dd>{formatCountEstimate(dataset.object_count_estimate)} (estimate)</dd>
        </div>
        <div>
          <dt>Total size</dt>
          <dd>{formatBytesEstimate(dataset.total_size_bytes_estimate)} (estimate)</dd>
        </div>
      </dl>

      {dataset.sample_key_prefixes && dataset.sample_key_prefixes.length > 0 && (
        <div className="no-schema-block__prefixes">
          <p>Sample key prefixes:</p>
          <ul>
            {dataset.sample_key_prefixes.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
