import pytest
from sqlalchemy import inspect, text
from alembic.config import Config
from alembic import command

@pytest.fixture
def alembic_cfg():
    cfg = Config("backend/alembic.ini")
    cfg.set_main_option("script_location", "backend/alembic")
    return cfg

def test_0009_swaps_rules_for_action_and_filter(alembic_cfg, db_engine_sync):
    command.upgrade(alembic_cfg, "0008")
    command.upgrade(alembic_cfg, "0009")
    cols = [c["name"] for c in inspect(db_engine_sync).get_columns("triggers")]
    assert "rules" not in cols
    assert "action" in cols
    assert "file_filter" in cols

def test_0009_wipes_existing_triggers(alembic_cfg, db_engine_sync):
    # First upgrade to 0008 to get the triggers table + rules column
    command.upgrade(alembic_cfg, "0008")
    # seed a trigger under the 0008 schema, then upgrade
    with db_engine_sync.begin() as conn:
        conn.execute(text(
            "INSERT INTO triggers (id,name,type,config,rules,enabled,created_at,updated_at) "
            "VALUES ('t1','x','watch','{}'::jsonb,'[]'::jsonb,true,now(),now())"))
    command.upgrade(alembic_cfg, "0009")
    with db_engine_sync.begin() as conn:
        n = conn.execute(text("SELECT count(*) FROM triggers")).scalar_one()
    assert n == 0

def test_0009_downgrade_restores_rules(alembic_cfg, db_engine_sync):
    command.upgrade(alembic_cfg, "0008")
    command.upgrade(alembic_cfg, "0009")
    command.downgrade(alembic_cfg, "0008")
    cols = [c["name"] for c in inspect(db_engine_sync).get_columns("triggers")]
    assert "rules" in cols
    assert "action" not in cols
