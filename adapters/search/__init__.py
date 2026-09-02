from adapters.search.base import BaseSearchAdapter, SearchResultItem
from adapters.search.google_patents import GooglePatentsSearchAdapter
from adapters.search.openalex import OpenAlexSearchAdapter
from adapters.search.epo import EpoSearchAdapter
from adapters.search.uspto import UsptoSearchAdapter

__all__ = [
    "BaseSearchAdapter",
    "SearchResultItem",
    "GooglePatentsSearchAdapter",
    "OpenAlexSearchAdapter",
    "EpoSearchAdapter",
    "UsptoSearchAdapter",
]
