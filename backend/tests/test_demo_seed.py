import asyncio

from database import postgres


class FakeSeedConn:
    def __init__(self):
        self.users = set()

    async def execute(self, query, user_id, username, password_hash, role, display_name):
        self.users.add(username)

    async def fetchval(self, query, usernames):
        return len(self.users.intersection(usernames))


def test_demo_staff_seed_is_idempotent():
    async def run():
        conn = FakeSeedConn()

        first_count = await postgres.seed_demo_staff_users(conn)
        second_count = await postgres.seed_demo_staff_users(conn)

        expected = {user[0] for user in postgres.DEV_STAFF_USERS}
        assert first_count == len(expected)
        assert second_count == len(expected)
        assert conn.users == expected

    asyncio.run(run())
