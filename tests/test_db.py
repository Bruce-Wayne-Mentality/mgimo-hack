import asyncio
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select

from hse_schedule import student_requests  # noqa: F401  (registers request tables)
from hse_schedule.accounts.models import Faculty, StudyGroup, User
from hse_schedule.accounts.seed import DEMO_ACCOUNTS, seed_demo
from hse_schedule.db import Base, Database, async_database_url, uuid7
from hse_schedule.migrate import downgrade, upgrade


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temporary, ignore_errors=True)
        self.url = f"sqlite:///{(self.temporary / 'db.sqlite3').as_posix()}"

    def test_migrations_build_exactly_the_model_schema(self):
        upgrade(self.url)

        async def diff():
            database = Database(self.url)
            async with database.engine.connect() as connection:
                result = await connection.run_sync(
                    lambda sync: compare_metadata(MigrationContext.configure(sync), Base.metadata)
                )
            await database.dispose()
            return result

        self.assertEqual(asyncio.run(diff()), [])
        downgrade(self.url, "base")
        upgrade(self.url)

    def test_seed_is_idempotent_and_matches_published_demo_accounts(self):
        upgrade(self.url)
        database = Database(self.url)

        async def run():
            first = await seed_demo(database)
            second = await seed_demo(database)
            async with database.session() as db:
                logins = set((await db.scalars(select(User.login))).all())
                faculties = len((await db.scalars(select(Faculty))).all())
                groups = len((await db.scalars(select(StudyGroup))).all())
            await database.dispose()
            return first, second, logins, faculties, groups

        first, second, logins, faculties, groups = asyncio.run(run())
        self.assertEqual(first["users"], 5)
        self.assertEqual(second, {"faculties": 0, "groups": 0, "users": 0})
        self.assertEqual(logins, {account["login"] for account in DEMO_ACCOUNTS})
        self.assertEqual((faculties, groups), (2, 4))

    def test_uuid7_is_version_seven_and_time_ordered(self):
        values = [uuid7() for _ in range(50)]
        self.assertTrue(all(value.version == 7 and value.variant == uuid.RFC_4122 for value in values))
        self.assertEqual(len(set(values)), 50)
        self.assertLessEqual(values[0].int >> 80, values[-1].int >> 80)

    def test_database_urls_get_async_drivers(self):
        self.assertEqual(async_database_url("postgresql://u:p@h/db"), "postgresql+asyncpg://u:p@h/db")
        self.assertEqual(async_database_url("sqlite:///x.db"), "sqlite+aiosqlite:///x.db")


if __name__ == "__main__":
    unittest.main()
