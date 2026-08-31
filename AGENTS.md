# PatentEvidence contributor guidance

PatentEvidence is an independent commercial repository. Do not import Git
history, credentials, runtime data, databases, cookies, real case files, or
generated artifacts from source repositories.

Keep P0 limited to runnable process and governance scaffolding. Product work
must preserve tenant isolation, provenance, immutable approval boundaries, and
the CNIPR manual-handoff constraint described in the product specification.

Before committing, run the validation commands in `README.md`. Never commit
`.env`, secrets, local runtime data, or the `.superpowers/` workspace.
