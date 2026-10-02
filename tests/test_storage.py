import json
import socket
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reactionding import storage  # noqa: E402


class FakeDB:
    """Just enough of pymysql for MariaDBStore (documents + history tables)."""

    class Error(Exception):
        pass

    def __init__(self, password=""):
        self.password = password
        self.docs, self.history, self.databases = {}, [], set()

    def module(self):
        db = self
        mod = types.SimpleNamespace(MySQLError=FakeDB.Error)

        def connect(**kw):
            if kw["password"] != db.password:
                raise FakeDB.Error(1045, "Access denied")
            return Conn(db)
        mod.connect = connect
        return mod


class Conn:
    def __init__(self, db):
        self.db = db

    def cursor(self):
        return Cursor(self.db)

    def commit(self):
        pass

    def close(self):
        pass


class Cursor:
    def __init__(self, db):
        self.db, self.row = db, None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, args=()):
        if sql.startswith("CREATE DATABASE"):
            self.db.databases.add(sql.split("`")[1])
        elif sql.startswith("USE"):
            if sql.split("`")[1] not in self.db.databases:
                raise FakeDB.Error(1049, "Unknown database")
        elif sql == "SELECT VERSION()":
            self.row = ("11.4.2-MariaDB",)
        elif sql.startswith("SELECT data FROM documents"):
            self.row = (self.db.docs[args[0]],) if args[0] in self.db.docs else None
        elif sql.startswith("INSERT INTO documents"):
            self.db.docs[args[0]] = args[1]
        elif sql.startswith("INSERT INTO history"):
            self.db.history.append(args)

    def fetchone(self):
        return self.row


class ListeningPort:
    def __enter__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        return self.sock.getsockname()[1]

    def __exit__(self, *exc):
        self.sock.close()


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / "data"
        patcher = mock.patch.object(storage, "program_dir", return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_folder_without_database(self):
        with mock.patch.object(storage, "SEARCH_PORTS", ()):
            st = storage.Storage(self.folder)
        self.assertEqual(st.status()["kind"], "folder")
        st.put("campaign", {"months": [1]})
        self.assertEqual(json.loads((self.folder / "campaign.json").read_text())["months"], [1])
        self.assertEqual(st.get("campaign")["months"], [1])
        self.assertEqual(st.get("planner", {"x": 1}), {"x": 1})

    def test_old_files_are_migrated(self):
        Path(self.tmp.name, "campaign.json").write_text('{"months": ["old"]}')
        with mock.patch.object(storage, "SEARCH_PORTS", ()):
            st = storage.Storage(self.folder)
        self.assertEqual(st.get("campaign")["months"], ["old"])
        self.assertTrue(st.migrated)

    def test_mariadb_found_on_this_pc(self):
        fake = FakeDB()
        with ListeningPort() as port, mock.patch.object(storage, "SEARCH_PORTS", (port,)), \
                mock.patch.object(storage, "_driver", return_value=fake.module()):
            self.folder.mkdir(parents=True)
            (self.folder / "settings.json").write_text('{"system": "Jita"}')
            st = storage.Storage(self.folder)
            info = st.status()
            self.assertEqual(info["kind"], "mariadb", info["note"])
            self.assertIn("eve_reaction_ding", fake.databases)
            # existing folder data is taken over by the new database
            self.assertEqual(json.loads(fake.docs["settings"])["system"], "Jita")
            st.put("campaign", {"months": [2]})
            self.assertEqual(json.loads(fake.docs["campaign"])["months"], [2])
            self.assertEqual(len(fake.history), 1)
            # folder keeps a backup copy
            self.assertTrue((self.folder / "campaign.json").exists())

    def test_wrong_login_falls_back_to_folder(self):
        fake = FakeDB(password="secret")
        with ListeningPort() as port, mock.patch.object(storage, "SEARCH_PORTS", (port,)), \
                mock.patch.object(storage, "_driver", return_value=fake.module()):
            st = storage.Storage(self.folder)
            self.assertEqual(st.status()["kind"], "folder")
            self.assertIn("login refused", st.note)
            storage.save_db_config(self.folder, {"port": port, "password": "secret"})
            self.assertEqual(st.reconnect()["kind"], "mariadb")
            self.assertFalse(st.status()["config"].get("password"))
            self.assertTrue(st.status()["config"]["hasPassword"])

    def test_switched_off(self):
        storage.save_db_config(self.folder, {"enabled": False})
        st = storage.Storage(self.folder)
        self.assertEqual(st.status()["kind"], "folder")
        self.assertIn("off", st.note)


if __name__ == "__main__":
    unittest.main()
