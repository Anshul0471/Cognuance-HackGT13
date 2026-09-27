"""Migrations against real PostgreSQL (guide 07 §4.5): empty DB → head, previous revision → head,
second upgrade is a no-op, no model/migration drift, key constraints/indexes exist."""

from alembic import command
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from tests.integration.throwaway import alembic_config, throwaway_database, upgrade


def _current(url) -> str | None:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def test_empty_database_to_head_is_idempotent_and_drift_free():
    with throwaway_database("cognuance_test_migrations") as url:
        config = alembic_config(url)
        head = ScriptDirectory.from_config(config).get_current_head()
        upgrade(url)
        assert _current(url) == head
        upgrade(url)  # second upgrade: no-op
        assert _current(url) == head
        command.check(config)  # raises if models and migrations disagree

        engine = create_engine(url)
        try:
            insp = inspect(engine)
            tables = set(insp.get_table_names())
            assert {
                "users",
                "patient_profiles",
                "doctor_patient_assignments",
                "assessment_sessions",
                "assessments",
                "context_checkins",
                "forecasts",
                "analyses",
                "alerts",
                "alert_events",
                "auth_sessions",
                "audit_events",
                "model_versions",
                "anomaly_policies",
                "alembic_version",
            } <= tables
            uniques = {t: [set(u["column_names"]) for u in insp.get_unique_constraints(t)] for t in tables}
            assert {"patient_id", "submission_key"} in uniques["assessments"]
            assert {"alert_id", "request_key"} in uniques["alert_events"]
            assert {"doctor_user_id", "patient_id"} in uniques["doctor_patient_assignments"]
            assert any({"session_id"} == u for u in uniques["forecasts"])
            # One weekly representative per (patient, slot): a partial unique index.
            rep = [
                i
                for i in insp.get_indexes("assessments")
                if i["unique"] and set(i["column_names"]) == {"patient_id", "slot_index"}
            ]
            assert rep and rep[0].get("dialect_options", {}).get("postgresql_where") is not None
        finally:
            engine.dispose()


def test_previous_revision_upgrades_with_existing_rows():
    with throwaway_database("cognuance_test_migrations") as url:
        config = alembic_config(url)
        script = ScriptDirectory.from_config(config)
        head = script.get_revision(script.get_current_head())
        previous = head.down_revision
        assert isinstance(previous, str)
        upgrade(url, previous)
        engine = create_engine(url)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO users (email, password_hash, role, display_name) "
                        "VALUES ('kept@demo.test', 'x', 'doctor', 'Kept Doctor')"
                    )
                )
            upgrade(url)
            assert _current(url) == head.revision
            with engine.connect() as conn:
                assert conn.scalar(text("SELECT count(*) FROM users WHERE email = 'kept@demo.test'")) == 1
        finally:
            engine.dispose()
