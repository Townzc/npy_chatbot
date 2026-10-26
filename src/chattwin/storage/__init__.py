"""SQLite storage; JSON payloads preserve versioned domain contracts."""

import os
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    event,
    text,
)

metadata = MetaData()
personas = Table(
    "personas",
    metadata,
    Column("id", String, primary_key=True),
    Column("payload", JSON, nullable=False),
)
relationships = Table(
    "relationships",
    metadata,
    Column("id", String, primary_key=True),
    Column("persona_id", ForeignKey("personas.id"), nullable=False),
    Column("payload", JSON, nullable=False),
)
imports = Table(
    "import_batches",
    metadata,
    Column("id", String, primary_key=True),
    Column("file_sha256", String, nullable=False),
    Column("payload", JSON, nullable=False),
)
messages = Table(
    "messages",
    metadata,
    Column("id", String, primary_key=True),
    Column("dedup_key", String, unique=True, nullable=False),
    Column("batch_id", ForeignKey("import_batches.id"), nullable=False),
    Column("conversation_id", String, nullable=False),
    Column("occurred_at", String, nullable=False),
    Column("payload", JSON, nullable=False),
)
uses = Table(
    "message_uses",
    metadata,
    Column("message_id", ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True),
    Column("persona_id", ForeignKey("personas.id"), primary_key=True),
    Column("relationship_id", ForeignKey("relationships.id")),
    Column("payload", JSON, nullable=False),
)
identity_links = Table(
    "identity_links",
    metadata,
    Column("id", String, primary_key=True),
    Column("persona_id", ForeignKey("personas.id"), nullable=False),
    Column("source_account_id", String, nullable=False),
    Column("sender_id", String, nullable=False),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("persona_id", "source_account_id", "sender_id"),
)


def scoped_table(name):
    return Table(
        name,
        metadata,
        Column("id", String, primary_key=True),
        Column("persona_id", ForeignKey("personas.id"), nullable=False),
        Column("relationship_id", ForeignKey("relationships.id"), nullable=False),
        Column("payload", JSON, nullable=False),
    )


styles = scoped_table("style_profiles")
memories = scoped_table("memory_items")
datasets = scoped_table("dataset_versions")
artifacts = scoped_table("model_artifacts")
model_deployments = Table(
    "model_deployments",
    metadata,
    Column("id", String, primary_key=True),
    Column("persona_id", ForeignKey("personas.id"), nullable=False),
    Column("relationship_id", ForeignKey("relationships.id"), nullable=False),
    Column("artifact_id", ForeignKey("model_artifacts.id")),
    Column("status", String, nullable=False),
    Column("payload", JSON, nullable=False),
)
bindings = Table(
    "bindings",
    metadata,
    Column("id", String, primary_key=True),
    Column("persona_id", ForeignKey("personas.id"), nullable=False),
    Column("relationship_id", ForeignKey("relationships.id"), nullable=False),
    Column("channel_account_id", String, nullable=False),
    Column("conversation_id", String, nullable=False),
    Column("active", Boolean, default=True, nullable=False),
    Column("payload", JSON, nullable=False),
)
Index(
    "uq_active_binding",
    bindings.c.channel_account_id,
    bindings.c.conversation_id,
    unique=True,
    sqlite_where=bindings.c.active.is_(True),
)
sessions = Table(
    "mode_sessions",
    metadata,
    Column("binding_id", ForeignKey("bindings.id"), primary_key=True),
    Column("mode", String, nullable=False),
    Column("control_epoch", Integer, nullable=False, default=0),
    Column("context_seq", Integer, nullable=False, default=0),
    Column("payload", JSON, nullable=False),
)
transitions = Table(
    "mode_transitions",
    metadata,
    Column("id", String, primary_key=True),
    Column("binding_id", ForeignKey("bindings.id"), nullable=False),
    Column("command_id", String, unique=True, nullable=False),
    Column("payload", JSON, nullable=False),
)
outbox = Table(
    "outbox",
    metadata,
    Column("id", String, primary_key=True),
    Column("binding_id", ForeignKey("bindings.id"), nullable=False),
    Column("transition_id", ForeignKey("mode_transitions.id")),
    Column("kind", String, nullable=False),
    Column("status", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("transition_id", "kind"),
)
inbound = Table(
    "inbound_events",
    metadata,
    Column("id", String, primary_key=True),
    Column("binding_id", ForeignKey("bindings.id"), nullable=False),
    Column("payload", JSON, nullable=False),
)
jobs = Table(
    "jobs",
    metadata,
    Column("id", String, primary_key=True),
    Column("kind", String, nullable=False),
    Column("status", String, nullable=False),
    Column("payload", JSON, nullable=False),
)
audit = Table(
    "audit_events",
    metadata,
    Column("id", String, primary_key=True),
    Column("kind", String, nullable=False),
    Column("payload", JSON, nullable=False),
)
usage = Table(
    "usage_records",
    metadata,
    Column("id", String, primary_key=True),
    Column("persona_id", String, nullable=False),
    Column("payload", JSON, nullable=False),
)
for table in (uses, styles, memories, datasets, artifacts, model_deployments, bindings):
    Index(f"ix_{table.name}_scope", table.c.persona_id, table.c.relationship_id)
Index("ix_outbox_binding_status", outbox.c.binding_id, outbox.c.status)
Index("ix_messages_conversation_time", messages.c.conversation_id, messages.c.occurred_at)


def default_data_dir() -> Path:
    return Path(
        os.environ.get("CHATTWIN_DATA_DIR", "~/Library/Application Support/ChatTwin")
    ).expanduser()


class Store:
    def __init__(self, path: Path | str | None = None):
        self.root = Path(path or default_data_dir()).expanduser().resolve()
        if any((parent / ".git").exists() for parent in (self.root, *self.root.parents)):
            raise ValueError("Private data directory must be outside every Git checkout")
        if self.root in (Path.home(), Path(self.root.anchor)):
            raise ValueError("Choose a dedicated private data directory")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.path = self.root / "chattwin.sqlite3"
        self.engine = create_engine(
            f"sqlite:///{self.path}", connect_args={"check_same_thread": False, "timeout": 10}
        )

        @event.listens_for(self.engine, "connect")
        def configure(dbapi, _):
            dbapi.execute("PRAGMA foreign_keys=ON")
            dbapi.execute("PRAGMA journal_mode=WAL")
            dbapi.execute("PRAGMA busy_timeout=10000")

    def migrate(self):
        from alembic import command
        from alembic.config import Config

        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{self.path}")
        with self.engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        self.path.chmod(0o600)

    @contextmanager
    def transaction(self):
        with self.engine.connect() as conn:
            conn.execute(text("BEGIN IMMEDIATE"))
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def rows(self, table, *conditions):
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(table.select().where(*conditions)).mappings()]

    def close(self):
        self.engine.dispose()

    def instance_lock(self):
        """Owner API and offline mutators share one instance lease."""
        return FileLock(self.root / "application.lock", timeout=0)
