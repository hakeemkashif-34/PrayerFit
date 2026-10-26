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
        # Up to this migration only, so later ones don't change what's checked.
        command.upgrade(config, "0004")

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
    finally:
        command.upgrade(config, "head")


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
        # Up to this migration only, so later ones don't change what's checked.
        command.upgrade(config, "0005")

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
    finally:
        command.upgrade(config, "head")


def test_migration_0006_keeps_data_and_copies_how_early(db):
    """Each user's Jumuah "how early" starts as their prayer "how early". The methods are dropped."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect, text

    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    command.downgrade(config, "0005")
    try:
        with db.begin() as connection:
            connection.execute(text("""
                INSERT INTO users (id, google_sub, email) VALUES
                    ('00000000-0000-0000-0000-0000000000b1', 'early-12', 'a@example.com'),
                    ('00000000-0000-0000-0000-0000000000b2', 'early-0', 'b@example.com');
                INSERT INTO masjids (id, source, osm_type, osm_id, name, updated_at) VALUES
                    ('00000000-0000-0000-0000-0000000000d1', 'openstreetmap', 'node', 1, 'Kanata Muslim Association', now());
                INSERT INTO user_settings (id, user_id, main_masjid_choice, main_masjid_id, main_masjid_short_name,
                                           method, asr_method, jumuah_saved, optional_saved, arrive_early_minutes,
                                           updated_at) VALUES
                    (gen_random_uuid(), '00000000-0000-0000-0000-0000000000b1', 'masjid',
                     '00000000-0000-0000-0000-0000000000d1', 'KMA', 'mwl', 'hanafi', true, true, 12, now()),
                    (gen_random_uuid(), '00000000-0000-0000-0000-0000000000b2', 'home', NULL, NULL,
                     NULL, NULL, true, true, 0, now());
            """))
        # Up to this migration only, so later ones don't change what's checked.
        command.upgrade(config, "0006")

        with db.connect() as connection:
            settings = connection.execute(text(
                "SELECT u.google_sub, s.main_masjid_short_name, s.arrive_early_minutes, s.jumuah_arrive_early_minutes, "
                "s.jumuah_pick_masjid_id, s.jumuah_pick_order FROM user_settings s JOIN users u ON u.id = s.user_id "
                "ORDER BY u.google_sub"
            )).all()
            jumuah_minutes = connection.execute(text("SELECT jumuah_minutes FROM masjids")).scalars().all()
        assert settings == [("early-0", None, 0, 0, None, None), ("early-12", "KMA", 12, 12, None, None)]
        # No Jumuah length yet, so 45 minutes (estimated) is used.
        assert jumuah_minutes == [None]
        columns = {c["name"] for c in inspect(db).get_columns("user_settings")}
        assert not {"method", "asr_method"} & columns
    finally:
        command.upgrade(config, "head")


def test_migration_0010_keeps_jumuah_at_the_main_masjid(db):
    """Extra Jumuah masjids go. A pick at the main masjid stays. Any other pick resets to the 1st Jumuah."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect, text

    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    command.downgrade(config, "0009")
    try:
        with db.begin() as connection:
            connection.execute(text("""
                INSERT INTO users (id, google_sub, email) VALUES
                    ('00000000-0000-0000-0000-0000000000e1', 'pick-at-main', 'a@example.com'),
                    ('00000000-0000-0000-0000-0000000000e2', 'pick-elsewhere', 'b@example.com'),
                    ('00000000-0000-0000-0000-0000000000e3', 'no-pick', 'c@example.com'),
                    ('00000000-0000-0000-0000-0000000000e4', 'at-home', 'd@example.com');
                INSERT INTO masjids (id, source, osm_type, osm_id, name, updated_at) VALUES
                    ('00000000-0000-0000-0000-0000000000f1', 'openstreetmap', 'node', 1, 'Kanata Muslim Association', now()),
                    ('00000000-0000-0000-0000-0000000000f2', 'openstreetmap', 'node', 2, 'Jamia Omar', now());
                INSERT INTO user_settings (id, user_id, main_masjid_choice, main_masjid_id, jumuah_saved, optional_saved,
                                           jumuah_pick_masjid_id, jumuah_pick_order, updated_at) VALUES
                    (gen_random_uuid(), '00000000-0000-0000-0000-0000000000e1', 'masjid',
                     '00000000-0000-0000-0000-0000000000f1', true, true, '00000000-0000-0000-0000-0000000000f1', 2, now()),
                    (gen_random_uuid(), '00000000-0000-0000-0000-0000000000e2', 'masjid',
                     '00000000-0000-0000-0000-0000000000f1', true, true, '00000000-0000-0000-0000-0000000000f2', 3, now()),
                    (gen_random_uuid(), '00000000-0000-0000-0000-0000000000e3', 'masjid',
                     '00000000-0000-0000-0000-0000000000f1', true, true, NULL, NULL, now()),
                    (gen_random_uuid(), '00000000-0000-0000-0000-0000000000e4', 'home', NULL, true, true,
                     '00000000-0000-0000-0000-0000000000f2', 1, now());
                INSERT INTO user_jumuah_masjids (user_id, masjid_id, position) VALUES
                    ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000f1', 0),
                    ('00000000-0000-0000-0000-0000000000e2', '00000000-0000-0000-0000-0000000000f2', 0),
                    ('00000000-0000-0000-0000-0000000000e2', '00000000-0000-0000-0000-0000000000f1', 1),
                    ('00000000-0000-0000-0000-0000000000e4', '00000000-0000-0000-0000-0000000000f2', 0);
            """))
    finally:
        command.upgrade(config, "head")

    with db.connect() as connection:
        picks = connection.execute(text(
            "SELECT u.google_sub, m.name, s.jumuah_pick_order FROM user_settings s JOIN users u ON u.id = s.user_id "
            "LEFT JOIN masjids m ON m.id = s.jumuah_pick_masjid_id ORDER BY u.google_sub"
        )).all()
    assert picks == [
        ("at-home", None, None),  # praying at home means no Jumuah
        ("no-pick", "Kanata Muslim Association", 1),  # the 1st Jumuah at the main masjid
        ("pick-at-main", "Kanata Muslim Association", 2),  # kept
        ("pick-elsewhere", "Kanata Muslim Association", 1),  # reset to the 1st Jumuah
    ]
    tables = set(inspect(db).get_table_names())
    assert "user_jumuah_masjids" not in tables
    assert "jumuah_saved" not in {c["name"] for c in inspect(db).get_columns("user_settings")}


def test_migration_0011_marks_existing_links_as_mine(db):
    """Links made before automatic matching were all made with link-mawaqit, so they're "admin"."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect, text

    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    command.downgrade(config, "0010")
    try:
        assert "mawaqit_list" not in inspect(db).get_table_names()
        with db.begin() as connection:
            connection.execute(text("""
                INSERT INTO masjids (id, source, osm_type, osm_id, name, updated_at) VALUES
                    ('00000000-0000-0000-0000-0000000000f1', 'openstreetmap', 'node', 1, 'Kanata Muslim Association', now());
                INSERT INTO masjid_sources (masjid_id, source, external_id, linked_at, consecutive_failures) VALUES
                    ('00000000-0000-0000-0000-0000000000f1', 'mawaqit', 'kma-kanata', now(), 0);
            """))
        command.upgrade(config, "0011")
        with db.connect() as connection:
            link = connection.execute(text(
                "SELECT external_id, origin, list_external_id, match_distance_m FROM masjid_sources"
            )).one()
            no_auto_link = connection.execute(text("SELECT no_auto_link FROM masjids")).scalar_one()
            listed = connection.execute(text("SELECT count(*) FROM mawaqit_list")).scalar_one()
        assert tuple(link) == ("kma-kanata", "admin", None, None)
        assert no_auto_link is False
        # The list itself is loaded from the CSV when the app starts, not by the migration.
        assert listed == 0
    finally:
        command.upgrade(config, "head")


def test_migration_0013_counts_existing_users_by_sign_up_hour(db):
    """Today's users fill the new table by the hour they signed up. No IDs or emails go in."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    command.downgrade(config, "0012")
    try:
        with db.begin() as connection:
            connection.execute(text("""
                INSERT INTO users (id, google_sub, email, created_at) VALUES
                    (gen_random_uuid(), 'a', 'a@example.com', '2026-10-25 14:10:00+00'),
                    (gen_random_uuid(), 'b', 'b@example.com', '2026-10-25 14:50:00+00'),
                    (gen_random_uuid(), 'c', 'c@example.com', '2026-10-25 15:05:00+00'),
                    -- 1:30 am on Nov 1 in Toronto, the hour that happens twice. The second one, in EST.
                    (gen_random_uuid(), 'd', 'd@example.com', '2026-11-01 01:30:00-05');
            """))
        command.upgrade(config, "0013")

        with db.connect() as connection:
            columns = connection.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'user_count_changes' ORDER BY 1"
            )).scalars().all()
            rows = connection.execute(text(
                "SELECT to_char(hour AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI'), signed_up, deleted "
                "FROM user_count_changes ORDER BY hour"
            )).all()
        # Only the hour and the counts. Nothing leads back to a person.
        assert columns == ["deleted", "hour", "signed_up"]
        assert rows == [
            ("2026-10-25 14:00", 2, 0),
            ("2026-10-25 15:00", 1, 0),
            ("2026-11-01 06:00", 1, 0),
        ]
    finally:
        command.upgrade(config, "head")
