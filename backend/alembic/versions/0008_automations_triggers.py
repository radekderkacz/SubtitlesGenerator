"""Automations triggers + trigger_events; drop Settings.watch_folders.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-20

Downgrade rebuilds `settings.watch_folders` from `triggers WHERE type='watch'`.
Rules richer than the original implicit shape are LOST on downgrade — this is
a recovery escape hatch, not a routine path.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "triggers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("rules", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("webhook_secret", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("type IN ('watch','cron','webhook')", name="triggers_type_chk"),
    )
    op.create_table(
        "trigger_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("trigger_id", sa.String(), sa.ForeignKey("triggers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("event_payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("matched_rule_index", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_trigger_events_trigger_fired", "trigger_events", ["trigger_id", sa.text("fired_at DESC")])
    op.create_index("ix_trigger_events_fired", "trigger_events", [sa.text("fired_at DESC")])

    # --- Data migration: Settings.watch_folders → Trigger(type='watch') rows ---
    import json, uuid as _uuid, os as _os
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, watch_folders, profiles FROM settings")).all()
    for settings_id, watch_folders, profiles in rows:
        wf = watch_folders or []
        profs = profiles or []
        first_profile = profs[0].get("name") if profs else None
        for path in wf:
            tid = str(_uuid.uuid4())
            name = _os.path.basename(path.rstrip("/")) or path
            if first_profile is None:
                conn.execute(sa.text("""
                    INSERT INTO triggers (id, name, type, config, rules, enabled, created_at, updated_at)
                    VALUES (:id, :name, 'watch', :config, '[]'::jsonb, false, now(), now())
                """), {"id": tid, "name": name, "config": json.dumps({"path": path})})
                print(f"alembic 0008 WARNING: watch folder '{path}' migrated as disabled (no profiles)")
                continue
            rule = {
                "glob": "**/*",
                "action": {
                    "profile_name": first_profile,
                    "source_language": None,
                    "target_language": None,
                    "skip_if_srt": True,
                },
            }
            conn.execute(sa.text("""
                INSERT INTO triggers (id, name, type, config, rules, enabled, created_at, updated_at)
                VALUES (:id, :name, 'watch', :config, :rules, true, now(), now())
            """), {"id": tid, "name": name, "config": json.dumps({"path": path}),
                   "rules": json.dumps([rule])})

    # --- Drop the legacy column ---
    op.drop_column("settings", "watch_folders")


def downgrade() -> None:
    op.add_column("settings", sa.Column("watch_folders", JSONB(), nullable=True))
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT config FROM triggers WHERE type='watch'")).all()
    paths = [r[0]["path"] for r in rows if r[0] and "path" in r[0]]
    if paths:
        import json
        conn.execute(sa.text("UPDATE settings SET watch_folders = :wf WHERE id=1"),
                     {"wf": json.dumps(paths)})
    # NOTE: rules richer than the original implicit shape are LOST on downgrade.
    op.drop_index("ix_trigger_events_fired", table_name="trigger_events")
    op.drop_index("ix_trigger_events_trigger_fired", table_name="trigger_events")
    op.drop_table("trigger_events")
    op.drop_table("triggers")
