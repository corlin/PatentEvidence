from adapters.search.base import BaseSearchAdapter, SearchResultItem
from adapters.search.google_patents import GooglePatentsSearchAdapter
from adapters.search.openalex import OpenAlexSearchAdapter

__all__ = [
    "BaseSearchAdapter",
    "SearchResultItem",
    "GooglePatentsSearchAdapter",
    "OpenAlexSearchAdapter",
]
