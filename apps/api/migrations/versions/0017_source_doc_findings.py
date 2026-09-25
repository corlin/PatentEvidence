"""Record active-content findings on uploaded source documents.

Revision ID: 0017_source_doc_findings
Revises: 0016_assessment_input_snapshots

Upload inspection (spec §6.2 step 2) rejects clearly weaponised files outright,
but accepts content that is common in real disclosures while still risky to
open — PDF JavaScript and attachments, DOCX OLE embeddings (MathType, Visio)
and ActiveX controls. Those findings are stored with the document so they stay
attributable to the exact uploaded file and can be shown to reviewers.

The column is written once at upload time; existing rows default to an empty
list (they predate inspection). Grants on the table are unchanged.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0017_source_doc_findings"
down_revision = "0016_assessment_input_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_documents",
        sa.Column(
            "security_findings",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("source_documents", "security_findings")
