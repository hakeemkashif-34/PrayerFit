"""Check the migrations build the same tables the models describe."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.models import Base


def test_migrations_match_the_models(db):
    with db.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    # Empty means nobody changed a model without adding a migration.
    assert differences == []


def test_migration_0004_keeps_existing_data(db):
    """Go back to milestone 4's tables, add a user like one from then, and upgrade again."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    command.downgrade(config, "0003")
    try:
        with db.begin() as connection:
            connection.execute(text("""
                INSERT INTO users (id, google_sub, email) VALUES
                    ('00000000-0000-0000-0000-00000000000a', 'old-user', 'old@example.com'),
                    ('00000000-0000-0000-0000-00000000000b', 'mid-setup', 'mid@example.com');
                INSERT INTO masjids (id, source, osm_type, osm_id, name, updated_at) VALUES
                    ('00000000-0000-0000-0000-0000000000c1', 'openstreetmap', 'node', 1, 'Stittsville Masjid', now()),
                    ('00000000-0000-0000-0000-0000000000c2', 'openstreetmap', 'node', 2, 'Jamia Omar', now()),
                    ('00000000-0000-0000-0000-0000000000c3', 'openstreetmap', 'node', 3, 'Kanata Muslim Association', now());
                INSERT INTO user_settings (id, user_id, time_zone, method, main_masjid_choice, main_masjid_id,
                                           main_masjid_short_name, jumuah_saved, setup_completed_at, updated_at) VALUES
                    (gen_random_uuid(), '00000000-0000-0000-0000-00000000000a', 'America/Toronto', 'mwl', 'masjid',
                     '00000000-0000-0000-0000-0000000000c3', 'KMA', true, now(), now()),
                    (gen_random_uuid(), '00000000-0000-0000-0000-00000000000b', NULL, NULL, NULL, NULL, NULL, false, NULL, now());
                INSERT INTO user_jumuah_masjids (user_id, masjid_id) VALUES
                    ('00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-0000000000c1'),
                    ('00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-0000000000c2');
                INSERT INTO prayer_events (id, user_id, local_date, prayer, starts_at, ends_at, time_zone,
                                           source_description, sync_status) VALUES
                    (gen_random_uuid(), '00000000-0000-0000-0000-00000000000a', '2026-10-24', 'isha',
                     now(), now(), 'America/Toronto', 'Calculated (ISNA, standard Asr)', 'synced');
            """))
    finally:
        command.upgrade(config, "head")

    with db.connect() as connection:
        settings = connection.execute(text(
            "SELECT user_id::text, main_masjid_short_name, optional_saved, arrive_early_minutes, "
            "prayer_color_id FROM user_settings ORDER BY user_id"
        )).all()
        jumuah = connection.execute(text(
            "SELECT m.name, j.position FROM user_jumuah_masjids j JOIN masjids m ON m.id = j.masjid_id ORDER BY j.position"
        )).all()
        events = connection.execute(text("SELECT prayer, kind FROM prayer_events")).all()
    assert settings == [
        ("00000000-0000-0000-0000-00000000000a", "KMA", True, 0, None),
        # Not finished setup yet, so the optional step is still ahead of them.
        ("00000000-0000-0000-0000-00000000000b", None, False, 0, None),
    ]
    # Numbered in name order, the order the settings page showed them in.
    assert jumuah == [("Jamia Omar", 0), ("Stittsville Masjid", 1)]
    assert events == [("isha", "prayer")]


def test_migration_0005_adds_the_main_masjid_as_the_jumuah_masjid(db):
    """Users from before: a main masjid and no Jumuah masjid gets one. Nobody else changes."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    command.downgrade(config, "0004")
    try:
        with db.begin() as connection:
            connection.execute(text("""
                INSERT INTO users (id, google_sub, email) VALUES
                    ('00000000-0000-0000-0000-0000000000a1', 'no-jumuah', 'a@example.com'),
                    ('00000000-0000-0000-0000-0000000000a2', 'own-jumuah', 'b@example.com'),
                    ('00000000-0000-0000-0000-0000000000a3', 'at-home', 'c@example.com');
                INSERT INTO masjids (id, source, osm_type, osm_id, name, updated_at) VALUES
                    ('00000000-0000-0000-0000-0000000000c1', 'openstreetmap', 'node', 1, 'Kanata Muslim Association', now()),
                    ('00000000-0000-0000-0000-0000000000c2', 'openstreetmap', 'node', 2, 'Jamia Omar', now());
                INSERT INTO user_settings (id, user_id, main_masjid_choice, main_masjid_id, jumuah_saved,
                                           optional_saved, arrive_early_minutes, updated_at) VALUES
                    (gen_random_uuid(), '00000000-0000-0000-0000-0000000000a1', 'masjid',
                     '00000000-0000-0000-0000-0000000000c1', false, true, 0, now()),
                    (gen_random_uuid(), '00000000-0000-0000-0000-0000000000a2', 'masjid',
                     '00000000-0000-0000-0000-0000000000c1', true, true, 0, now()),
                    (gen_random_uuid(), '00000000-0000-0000-0000-0000000000a3', 'home', NULL, false, true, 0, now());
                INSERT INTO user_jumuah_masjids (user_id, masjid_id, position) VALUES
                    ('00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-0000000000c2', 0);
            """))
    finally:
        command.upgrade(config, "head")

    with db.connect() as connection:
        jumuah = connection.execute(text(
            "SELECT u.google_sub, m.name, j.position FROM user_jumuah_masjids j "
            "JOIN users u ON u.id = j.user_id JOIN masjids m ON m.id = j.masjid_id ORDER BY u.google_sub"
        )).all()
        saved = dict(connection.execute(text(
            "SELECT u.google_sub, s.jumuah_saved FROM user_settings s JOIN users u ON u.id = s.user_id"
        )).all())
    assert jumuah == [
        ("no-jumuah", "Kanata Muslim Association", 0),  # added
        ("own-jumuah", "Jamia Omar", 0),  # their own list, unchanged
    ]
    assert saved == {"no-jumuah": True, "own-jumuah": True, "at-home": False}
