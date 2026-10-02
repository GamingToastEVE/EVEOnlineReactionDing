"""Where the program keeps its data: a local MariaDB (only if one is found) or a folder.

Three documents are stored, each as JSON: ``settings``, ``campaign`` (monthly
planner) and ``planner`` (one-off planner). On start the program looks for a
MariaDB/MySQL server on this PC (localhost:3306). It is used when a login works:
the login from ``database.json`` in the data folder, or ``root`` without a
password. The database ``eve_reaction_ding`` and its tables are created
automatically. Without a reachable database everything goes into the data
folder (``EVEReactionDing-data`` next to the .exe, ``data`` when run from source).
"""

import json
import os
import socket
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

DOCUMENTS = ("settings", "campaign", "planner")
DB_CONFIG = "database.json"
DEFAULT_DB = {"enabled": True, "host": "127.0.0.1", "port": 3306,
              "user": "root", "password": "", "database": "eve_reaction_ding"}
SEARCH_PORTS = (3306, 3307, 3308)  # usual MariaDB/MySQL ports on a PC (2nd instance, XAMPP ...)
HISTORY_KEEP = 50  # campaign snapshots kept in the database


def program_dir():
    """Folder of the .exe (frozen) or the current folder (source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def default_data_dir():
    env = os.environ.get("EVE_REACTION_DING_DATA")
    if env:
        return Path(env)
    base = program_dir()
    return base / ("EVEReactionDing-data" if getattr(sys, "frozen", False) else "data")


class StorageError(Exception):
    pass


# --- folder ------------------------------------------------------------------

class FolderStore:
    kind = "folder"

    def __init__(self, folder):
        self.folder = Path(folder)
        self.lock = threading.Lock()

    def path(self, name):
        return self.folder / f"{name}.json"

    def get(self, name):
        try:
            return json.loads(self.path(name).read_text("utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, name, value):
        with self.lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.path(name).with_suffix(".tmp")
            tmp.write_text(json.dumps(value, indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path(name))

    def describe(self):
        return {"kind": "folder", "location": str(self.folder.resolve())}


# --- MariaDB -------------------------------------------------------------------

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS documents (
        name VARCHAR(64) NOT NULL PRIMARY KEY,
        data LONGTEXT NOT NULL,
        updated_at DATETIME NOT NULL
    ) CHARACTER SET utf8mb4""",
    """CREATE TABLE IF NOT EXISTS history (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(64) NOT NULL,
        data LONGTEXT NOT NULL,
        saved_at DATETIME NOT NULL,
        INDEX (name, saved_at)
    ) CHARACTER SET utf8mb4""",
)


def port_open(host, port, timeout=0.4):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _driver():
    try:
        import pymysql
    except ImportError:
        return None
    return pymysql


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


class MariaDBStore:
    kind = "mariadb"

    def __init__(self, config):
        self.config = {**DEFAULT_DB, **(config or {})}
        self.lock = threading.Lock()
        self.version = ""
        with self.lock:
            conn = self._connect(create=True)
            try:
                with conn.cursor() as cur:
                    for statement in SCHEMA:
                        cur.execute(statement)
                    cur.execute("SELECT VERSION()")
                    self.version = cur.fetchone()[0]
                conn.commit()
            finally:
                conn.close()

    def _connect(self, create=False):
        pymysql = _driver()
        if pymysql is None:
            raise StorageError("Python package pymysql is missing (pip install pymysql)")
        c = self.config
        name = c["database"]
        if not name.replace("_", "").isalnum():
            raise StorageError(f"invalid database name {name!r}")
        try:
            conn = pymysql.connect(host=c["host"], port=int(c["port"]), user=c["user"],
                                   password=c["password"], charset="utf8mb4",
                                   connect_timeout=3, autocommit=False)
            with conn.cursor() as cur:
                if create:
                    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4")
                cur.execute(f"USE `{name}`")
            return conn
        except pymysql.MySQLError as exc:
            raise StorageError(_db_message(exc)) from exc

    def get(self, name):
        with self.lock:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT data FROM documents WHERE name=%s", (name,))
                    row = cur.fetchone()
            finally:
                conn.close()
        try:
            return json.loads(row[0]) if row else None
        except ValueError:
            return None

    def put(self, name, value):
        data = json.dumps(value, ensure_ascii=False)
        with self.lock:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT data FROM documents WHERE name=%s", (name,))
                    old = cur.fetchone()
                    if old and old[0] == data:
                        return
                    now = _now()
                    cur.execute("INSERT INTO documents (name, data, updated_at) VALUES (%s, %s, %s) "
                                "ON DUPLICATE KEY UPDATE data=VALUES(data), updated_at=VALUES(updated_at)",
                                (name, data, now))
                    if name == "campaign":
                        cur.execute("INSERT INTO history (name, data, saved_at) VALUES (%s, %s, %s)",
                                    (name, data, now))
                        cur.execute("DELETE FROM history WHERE name=%s AND id NOT IN (SELECT id FROM "
                                    "(SELECT id FROM history WHERE name=%s ORDER BY id DESC LIMIT %s) keep)",
                                    (name, name, HISTORY_KEEP))
                conn.commit()
            finally:
                conn.close()

    def describe(self):
        c = self.config
        return {"kind": "mariadb", "location": f"{c['user']}@{c['host']}:{c['port']}/{c['database']}",
                "version": self.version}


def _db_message(exc):
    args = getattr(exc, "args", ())
    code = args[0] if args and isinstance(args[0], int) else None
    if code == 1045:
        return "login refused (user/password wrong)"
    if code in (2003, 2002):
        return "no database server reachable"
    return str(args[1] if len(args) > 1 else exc)


# --- choosing the store ---------------------------------------------------------

def load_db_config(folder):
    try:
        values = json.loads((Path(folder) / DB_CONFIG).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return {**DEFAULT_DB, **{k: v for k, v in values.items() if k in DEFAULT_DB}}


def save_db_config(folder, config):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    values = {**DEFAULT_DB, **{k: v for k, v in (config or {}).items() if k in DEFAULT_DB}}
    values["port"] = int(values["port"])
    values["enabled"] = bool(values["enabled"])
    (folder / DB_CONFIG).write_text(json.dumps(values, indent=2), encoding="utf-8")
    return values


def try_mariadb(config):
    """(store, None) or (None, reason)."""
    config = {**DEFAULT_DB, **(config or {})}
    if not port_open(config["host"], config["port"]):
        return None, f"no MariaDB found on {config['host']}:{config['port']}"
    if _driver() is None:
        return None, "MariaDB found, but the Python package pymysql is missing"
    try:
        return MariaDBStore(config), None
    except StorageError as exc:
        return None, f"MariaDB found on {config['host']}:{config['port']}, but: {exc}"


class Storage:
    """Front object used by server and CLI. Picks MariaDB or the folder once at start."""

    def __init__(self, folder=None, detect=True):
        self.folder_store = FolderStore(folder or default_data_dir())
        self.store = self.folder_store
        self.note = ""
        self.found_port = None
        self.migrated = []
        self._migrate_old_files()
        if detect:
            self.reconnect()

    @property
    def folder(self):
        return self.folder_store.folder

    def reconnect(self, config=None):
        """Looks for MariaDB (saved login or root without password); folder otherwise."""
        saved = load_db_config(self.folder)
        config = config or saved
        if config and not config.get("enabled", True):
            self.store, self.note = self.folder_store, "MariaDB switched off - using the folder"
            return self.status()
        if config:
            store, reason = try_mariadb(config)
        else:
            store, reason = self._search()
        if store is None:
            self.store, self.note = self.folder_store, reason
            if saved:
                self.note += " - using the folder instead"
            return self.status()
        self.store, self.note = store, ""
        self._seed_database()
        return self.status()

    def _search(self):
        """No saved login: look for a server on this PC on the usual ports."""
        reasons = []
        for port in SEARCH_PORTS:
            if not port_open(DEFAULT_DB["host"], port):
                continue
            self.found_port = port
            store, reason = try_mariadb({**DEFAULT_DB, "port": port})
            if store:
                return store, None
            reasons.append(reason)
        if reasons:
            return None, "; ".join(reasons) + " - enter the login in the settings (Storage)"
        return None, "no MariaDB found on this PC (ports " + ", ".join(map(str, SEARCH_PORTS)) + ")"

    def _migrate_old_files(self):
        """Copies settings.json/campaign.json/planner.json from the program folder (old versions)."""
        for name in DOCUMENTS:
            if self.folder_store.path(name).exists():
                continue
            for old in (program_dir() / f"{name}.json", Path.cwd() / f"{name}.json"):
                if old.exists() and old.resolve() != self.folder_store.path(name).resolve():
                    try:
                        self.folder_store.put(name, json.loads(old.read_text("utf-8")))
                        self.migrated.append(str(old))
                    except (OSError, ValueError):
                        continue
                    break

    def _seed_database(self):
        """A fresh database takes over what is already in the folder."""
        for name in DOCUMENTS:
            if self.store.get(name) is None:
                value = self.folder_store.get(name)
                if value is not None:
                    self.store.put(name, value)

    def get(self, name, default=None):
        try:
            value = self.store.get(name)
        except StorageError as exc:
            self._fall_back(exc)
            value = self.store.get(name)
        return default if value is None else value

    def put(self, name, value):
        try:
            self.store.put(name, value)
        except StorageError as exc:
            self._fall_back(exc)
            self.store.put(name, value)
        if self.store is not self.folder_store:
            self.folder_store.put(name, value)  # backup copy, used if the database is gone

    def _fall_back(self, exc):
        self.store = self.folder_store
        self.note = f"MariaDB lost ({exc}) - saving into the folder"

    def status(self):
        info = self.store.describe()
        info["note"] = self.note
        info["folder"] = str(self.folder.resolve())
        cfg = load_db_config(self.folder) or {**DEFAULT_DB, "port": self.found_port or DEFAULT_DB["port"]}
        info["config"] = {k: v for k, v in cfg.items() if k != "password"}
        info["config"]["hasPassword"] = bool(cfg.get("password"))
        info["driver"] = _driver() is not None
        return info
