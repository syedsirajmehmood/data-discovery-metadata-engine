"""Make `relevance` importable as a top-level package for the test suite.

FE2 owns `control-plane/storage/` and `control-plane/storage/search/`
(everything outside this directory), and per architecture.md §8 this
directory has "zero required edits inside FE2's part of the tree" — so this
module does not create `__init__.py` files in those ancestor directories to
turn `control_plane.storage.search.relevance` into a real dotted package.

Instead, this conftest puts this directory's *parent* (`.../search/`) on
`sys.path` at test-collection time, so `relevance` resolves as a standalone
top-level package (`import relevance`, `from relevance import ...`) without
needing any file outside `relevance/` to exist. Once FE2's tree lands with
real `__init__.py` files up the chain, this becomes unnecessary (but
harmless) — `relevance` would then also be importable as
`control_plane.storage.search.relevance`.
"""

import sys
from pathlib import Path

_SEARCH_DIR = Path(__file__).resolve().parent.parent

if str(_SEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_SEARCH_DIR))
