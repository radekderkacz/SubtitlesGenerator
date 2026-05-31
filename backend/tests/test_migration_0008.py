import pytest
from sqlalchemy import inspect, text
from alembic.config import Config
from alembic import command

@pytest.fixture
def alembic_cfg(tmp_path):
    cfg = Config("backend/alembic.ini")
    cfg.set_main_option("script_location", "backend/alembic")
    return cfg

def test_0008_upgrade_creates_triggers_tables(alembic_cfg, db_engine_sync):
    command.upgrade(alembic_cfg, "0008")
    insp = inspect(db_engine_sync)
    assert "triggers" in insp.get_table_names()
    assert "trigger_events" in insp.get_table_names()
    # Settings.watch_folders column dropped
    cols = [c["name"] for c in insp.get_columns("settings")]
    assert "watch_folders" not in cols

def test_0008_downgrade_restores_watch_folders(alembic_cfg, db_engine_sync):
    command.upgrade(alembic_cfg, "0008")
    command.downgrade(alembic_cfg, "0007")
    insp = inspect(db_engine_sync)
    assert "triggers" not in insp.get_table_names()
    cols = [c["name"] for c in insp.get_columns("settings")]
    assert "watch_folders" in cols


def test_0008_data_migration_seeds_watch_triggers(alembic_cfg, db_engine_sync):
    with db_engine_sync.begin() as conn:
        conn.execute(text("""
            INSERT INTO settings (id, nas_mount_path, whisper_model, whisper_device,
                                  watch_folders, profiles, created_at, updated_at)
            VALUES (1, '/mnt/nas', 'large-v3', 'auto',
                    '["/shared/TV","/shared/Movies"]'::jsonb,
                    '[{"name":"Profile1"}]'::jsonb,
                    now(), now())
        """))
    command.upgrade(alembic_cfg, "0008")
    with db_engine_sync.begin() as conn:
        rows = conn.execute(text("SELECT name, config, rules, enabled FROM triggers WHERE type='watch' ORDER BY name")).all()
    assert [r[0] for r in rows] == ["Movies", "TV"]
    assert all(r[3] is True for r in rows)
    for r in rows:
        rules = r[2]
        assert len(rules) == 1
        action = rules[0]["action"]
        assert action["profile_name"] == "Profile1"
        assert action["target_language"] is None


def test_0008_data_migration_no_profile_disables_trigger(alembic_cfg, db_engine_sync):
    with db_engine_sync.begin() as conn:
        conn.execute(text("DELETE FROM settings"))
        conn.execute(text("""
            INSERT INTO settings (id, nas_mount_path, whisper_model, whisper_device,
                                  watch_folders, profiles, created_at, updated_at)
            VALUES (1, '/mnt/nas', 'large-v3', 'auto',
                    '["/shared/Orphan"]'::jsonb, '[]'::jsonb, now(), now())
        """))
    command.upgrade(alembic_cfg, "0008")
    with db_engine_sync.begin() as conn:
        row = conn.execute(text("SELECT enabled, rules FROM triggers WHERE name='Orphan'")).one()
    assert row[0] is False
    assert row[1] == []
