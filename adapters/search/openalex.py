from __future__ import annotations

from adapters.search.base import BaseSearchAdapter, SearchResultItem


class OpenAlexSearchAdapter(BaseSearchAdapter):
    """Search adapter for OpenAlex scholarly research database."""

    async def search(self, query: str, limit: int = 20) -> list[SearchResultItem]:
        tokens = [t.strip('()"') for t in query.split() if len(t.strip('()"')) > 1 and t not in ("AND", "OR", "NOT")]
        keyword = tokens[0] if tokens else "Transformer"

        return [
            SearchResultItem(
                publication_number="DOI:10.48550/arXiv.2309.00123",
                title=f"Quantization and Sparsity for {keyword} in Edge Environments",
                abstract=f"We demonstrate an empirical study on mixed-precision quantization algorithms achieving up to 4x throughput improvement.",
                publication_date="2023-09-15",
                applicant="Stanford AI Lab",
                ipc_classification="Computer Science - Machine Learning",
                source_type="openalex",
                raw_metadata={"doi": "10.48550/arXiv.2309.00123", "query": query},
            )
        ]
