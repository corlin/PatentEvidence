from alembic import op


def create_composite_organization_foreign_key(
    constraint_name: str,
    source_table: str,
    referent_table: str,
    *,
    source_id_column: str,
    referent_id_column: str = "id",
) -> None:
    op.create_foreign_key(
        constraint_name,
        source_table,
        referent_table,
        ["organization_id", source_id_column],
        ["organization_id", referent_id_column],
        ondelete="RESTRICT",
    )


def enable_force_rls(table_name: str, *, organization_column: str = "organization_id") -> None:
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'''CREATE POLICY {table_name}_tenant_isolation ON "{table_name}"
        TO patent_evidence_app, patent_evidence_worker
        USING ("{organization_column}" = nullif(
            current_setting('app.current_organization_id', true), ''
        )::uuid)
        WITH CHECK ("{organization_column}" = nullif(
            current_setting('app.current_organization_id', true), ''
        )::uuid)'''
    )
    op.execute(
        f'''CREATE POLICY {table_name}_migration_maintenance ON "{table_name}"
        TO patent_evidence_migration USING (true) WITH CHECK (true)'''
    )


def add_platform_policy(table_name: str) -> None:
    op.execute(
        f'''CREATE POLICY {table_name}_platform_access ON "{table_name}"
        TO patent_evidence_platform USING (true) WITH CHECK (true)'''
    )


def enable_force_session_token_rls(table_name: str) -> None:
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'''CREATE POLICY {table_name}_token_isolation ON "{table_name}"
        TO patent_evidence_app
        USING (token_hash = nullif(
            current_setting('app.current_session_token_hash', true), ''
        ))
        WITH CHECK (token_hash = nullif(
            current_setting('app.current_session_token_hash', true), ''
        ))'''
    )
    op.execute(
        f'''CREATE POLICY {table_name}_migration_maintenance ON "{table_name}"
        TO patent_evidence_migration USING (true) WITH CHECK (true)'''
    )
