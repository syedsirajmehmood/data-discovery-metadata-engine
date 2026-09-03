export function ErrorBanner({
  message,
  onRetry,
}: {
  message: string
  onRetry?: () => void
}) {
  return (
    <div className="error-banner" role="alert">
      <span>{message}</span>
      {onRetry ? (
        <button type="button" className="error-banner__retry" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  )
}
