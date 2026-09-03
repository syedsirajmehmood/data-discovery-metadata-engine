from storage.search.store import SearchIndex

__all__ = ["SearchIndex"]

# NOTE: control-plane/storage/search/relevance/ is the ML engineer's
# directory, per architecture.md §8. FE2 leaves it untouched — do not add an
# __init__.py or any file under relevance/ from this package.
