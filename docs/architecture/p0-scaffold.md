# P0 scaffold architecture

P0 establishes three independently runnable process surfaces: a FastAPI API,
a worker process, and a React/Vite web shell. The API health endpoint is
process-only and intentionally does not contact PostgreSQL or MinIO; dependency
readiness belongs to later application checks.

Compose provides PostgreSQL and MinIO with named volumes for local development.
The directory boundaries reserve modules for tenancy, cases, retrieval,
evidence, assessment, review, and delivery without implementing their business
logic. Adapter boundaries reserve EPO, USPTO, CNIPR handoff, object storage,
LLM, and secret-store integrations. In particular, CNIPR remains a future
manual visible-browser handoff contract only.
