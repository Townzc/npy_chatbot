import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from filelock import FileLock, Timeout

from chattwin.channels import FakeChannel
from chattwin.domain import Binding, ModeCommand
from chattwin.importers import DataService
from chattwin.ops import create_backup, inspect_backup, restore_backup
from chattwin.outbox import Coordinator
from chattwin.storage import Store, artifacts, bindings, messages, outbox, sessions


@pytest.fixture
def source(tmp_path):
    store = Store(tmp_path / "source")
    store.migrate()
    service = DataService(store)
    persona = service.create_persona("Synthetic backup persona")
    relationship = service.create_relationship(persona["id"], "Synthetic backup friend")
    fixture = Path(__file__).resolve().parents[1] / "examples/chatlab_wechat.synthetic.jsonl"
    service.import_file(
        fixture, persona["id"], relationship["id"], "demo_owner", "source", confirm_human=True
    )
    dataset = service.build_dataset(persona["id"], relationship["id"])
    yield store, service, persona["id"], relationship["id"], dataset
    store.close()


def reseal(path):
    manifest = json.loads((path / "backup-manifest.json").read_text())
    manifest.pop("manifest_hash")
    manifest["manifest_hash"] = hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (path / "backup-manifest.json").write_text(json.dumps(manifest))


def test_sqlite_wal_snapshot_and_dataset_restore(source, tmp_path):
    store, service, persona, relationship, dataset = source
    (store.root / "owner-token").write_text("synthetic-secret-not-for-backup")
    (store.root / "uploads").mkdir()
    (store.root / "uploads/private.json").write_text("excluded raw upload")
    backup = tmp_path / "backup"
    result = create_backup(store, backup)
    assert result["row_counts"]["messages"] == 4
    assert not (backup / "owner-token").exists()
    assert not (backup / "uploads").exists()
    service.add_memory(
        persona,
        relationship,
        "created after snapshot",
        [service.list_messages(persona, relationship)[0]["id"]],
    )
    assert inspect_backup(backup)["row_counts"]["memory_items"] == 0
    restored = tmp_path / "restored"
    assert restore_backup(backup, restored)["status"] == "restored_paused"
    target = Store(restored)
    target.migrate()
    assert target.rows(messages) == store.rows(messages)
    assert (restored / f"datasets/{dataset['id']}/manifest.json").read_bytes() == (
        store.root / f"datasets/{dataset['id']}/manifest.json"
    ).read_bytes()
    assert not (restored / "owner-token").exists()
    target.close()


async def test_restore_archives_bindings_cancels_unsent_and_preserves_unknown(source, tmp_path):
    store, _, persona, relationship, _ = source
    channel = FakeChannel(auto_confirm=False)
    coordinator = Coordinator(store, channel)
    coordinator.create_binding(
        Binding(
            id="binding",
            persona_id=persona,
            relationship_id=relationship,
            channel_account_id=channel.account_id,
            conversation_id="c",
            recipient_id="synthetic-friend",
        )
    )
    await coordinator.command(
        "binding", ModeCommand(command_id="enable", action="enable", expected_control_epoch=0)
    )
    await coordinator.drain()
    with store.transaction() as conn:
        conn.execute(
            outbox.insert().values(
                id="not-started",
                binding_id="binding",
                kind="ai_reply",
                status="planned",
                created_at="2026-10-26T00:00:00Z",
                payload={"text": "synthetic"},
            )
        )
    backup = tmp_path / "backup"
    create_backup(store, backup)
    target = tmp_path / "restored"
    restore_backup(backup, target)
    restored = Store(target)
    assert restored.rows(bindings)[0]["active"] is False
    assert restored.rows(sessions)[0]["mode"] == "PAUSED"
    assert {row["status"] for row in restored.rows(outbox)} == {"unknown", "cancelled"}
    assert restored.rows(sessions)[0]["payload"]["restore_requires_review"] is True
    restored.close()
    await coordinator.close()


def test_tamper_and_traversal_are_rejected_before_target_creation(source, tmp_path):
    backup = tmp_path / "backup"
    create_backup(source[0], backup)
    manifest_path = backup / "backup-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["../outside"] = {"sha256": "0" * 64, "size": 0}
    manifest_path.write_text(json.dumps(manifest))
    reseal(backup)
    target = tmp_path / "restore"
    with pytest.raises(ValueError, match="traversal"):
        restore_backup(backup, target)
    assert not target.exists()
    del manifest["files"]["../outside"]
    manifest_path.write_text(json.dumps(manifest))
    reseal(backup)
    (backup / "chattwin.sqlite3").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum"):
        inspect_backup(backup)


def test_symlink_files_never_followed(source, tmp_path):
    store, _, _, _, dataset = source
    train = store.root / f"datasets/{dataset['id']}/train.jsonl"
    real = tmp_path / "elsewhere"
    train.rename(real)
    train.symlink_to(real)
    backup = tmp_path / "backup"
    with pytest.raises(OSError):
        create_backup(store, backup)
    assert not backup.exists()
    train.unlink()
    real.rename(train)
    create_backup(store, backup)
    (backup / "unexpected-link").symlink_to(real)
    with pytest.raises(ValueError, match="symlink"):
        inspect_backup(backup)


def test_nonempty_target_and_maintenance_lock_refuse_restore(source, tmp_path):
    backup = tmp_path / "backup"
    create_backup(source[0], backup)
    target = tmp_path / "existing"
    target.mkdir()
    (target / "running.sender.lock").write_text("running instance marker")
    with pytest.raises(ValueError, match="empty target"):
        restore_backup(backup, target)
    assert (target / "running.sender.lock").read_text() == "running instance marker"
    empty = tmp_path / "empty"
    with FileLock(tmp_path / ".empty.maintenance.lock"):
        with pytest.raises(Timeout):
            restore_backup(backup, empty)
    assert not empty.exists()
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        restore_backup(backup, alias / "redirected")
    assert not (tmp_path / "redirected").exists()


def test_unsupported_sqlite_schema_refused_even_with_valid_file_checksum(source, tmp_path):
    backup = tmp_path / "backup"
    create_backup(source[0], backup)
    with sqlite3.connect(backup / "chattwin.sqlite3") as connection:
        connection.execute("UPDATE alembic_version SET version_num='9999'")
    data = (backup / "chattwin.sqlite3").read_bytes()
    manifest_path = backup / "backup-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["chattwin.sqlite3"] = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }
    manifest_path.write_text(json.dumps(manifest))
    reseal(backup)
    with pytest.raises(ValueError, match="schema revision"):
        inspect_backup(backup)


def test_model_metadata_included_but_weights_never_claimed_restored(source, tmp_path):
    store, _, persona, relationship, _ = source
    local = store.root / "artifacts/local-model"
    local.mkdir(parents=True)
    (local / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "persona_id": persona,
                "relationship_id": relationship,
                "base_model_id": "synthetic",
            }
        )
    )
    (local / "adapter_model.safetensors").write_bytes(b"synthetic fixture, not actual weights")
    with store.transaction() as conn:
        conn.execute(
            artifacts.insert().values(
                id="local-model",
                persona_id=persona,
                relationship_id=relationship,
                payload={"artifact_path": str(local)},
            )
        )
        conn.execute(
            artifacts.insert().values(
                id="external-model",
                persona_id=persona,
                relationship_id=relationship,
                payload={"artifact_path": str(tmp_path / "external")},
            )
        )
    backup = tmp_path / "backup"
    create_backup(store, backup)
    assert (backup / "model_manifests/local-model/manifest.json").exists()
    assert not list(backup.rglob("*.safetensors"))
    restored = tmp_path / "restored"
    result = restore_backup(backup, restored)
    assert result["model_weights_restored"] is False
    target = Store(restored)
    assert all(row["payload"]["restore_requires_verification"] for row in target.rows(artifacts))
    target.close()
