import json
from pathlib import Path

import pytest

from chattwin.domain import DomainError
from chattwin.importers import DataService, detect, inspect, parse
from chattwin.storage import Store, messages

FIXTURE = Path(__file__).resolve().parents[1] / "examples/qce_v6_3_2.synthetic.json"


def changed_file(tmp_path, change):
    document = json.loads(FIXTURE.read_text())
    change(document)
    path = tmp_path / "qce.json"
    path.write_text(json.dumps(document, ensure_ascii=False))
    return path


def test_qce_ms_identity_reply_and_nontext_boundaries():
    assert detect(FIXTURE) == "qce"
    report = inspect(FIXTURE)
    assert report["total"] == 8 and report["bad_rows"] == 0
    assert report["stable_id_coverage"] == 1
    assert report["types"] == {
        "text": 3,
        "unsupported": 2,
        "recalled": 1,
        "system": 1,
        "mode_notice": 1,
    }
    assert report["unresolved_references"] == 0
    assert report["start"] == "2026-10-26T00:00:00+00:00"
    assert report["format_compatibility"]["actual_release_verified"] is False
    assert {sender["id"] for sender in report["senders"]} == {"u_demo_owner", "u_demo_partner"}
    rows = [message for _, message, error in parse(FIXTURE) if not error]
    assert rows[2].content.text == "下午三点见。"
    assert rows[2].content.reply_to == "qce-demo-1"
    assert rows[1].sender_id == "u_demo_owner" and rows[1].origin == "unknown"
    assert rows[1].provenance["qce_sender_uin"] == "demo_owner_uin"
    assert rows[5].origin == "platform_system"
    assert "https://" not in str(rows[3].content.attachments)
    assert "rawMessage" not in str(rows[7].provenance)


def test_qce_import_confirmation_dedup_and_target_mask(tmp_path):
    store = Store(tmp_path / "private")
    store.migrate()
    try:
        data = DataService(store)
        persona = data.create_persona("QCE fictional owner")
        relationship = data.create_relationship(persona["id"], "QCE fictional friend")
        args = [persona["id"], relationship["id"], "u_demo_owner", "demo_source"]
        report = data.import_file(FIXTURE, *args)
        assert report["candidate_training_targets"] == 0
        copied = tmp_path / "same-content-new-file.json"
        copied.write_text("\ufeff" + FIXTURE.read_text())
        second = data.import_file(copied, *args, confirm_human=True)
        assert second["inserted"] == 0 and second["duplicates"] == 8
        assert len(store.rows(messages)) == 8
        system_message = next(
            row for row in data.list_messages(*args[:2]) if row["origin"] == "platform_system"
        )
        assert system_message["use_context"]["sender_role"] == "system"
        assert not any(system_message["use_context"]["use_policy"].values())
        dataset = data.build_dataset(persona["id"], relationship["id"])
        targets = [
            json.loads(line)["messages"][-1]["content"]
            for line in (Path(dataset["path"]) / "train.jsonl").read_text().splitlines()
        ]
        # Existing dataset builder combines consecutive owner turns in a segment.
        assert targets == ["好呀\n<b>这只是文字</b>\n下午三点见。"]
        assert all("引用预览" not in text and "本人已接管" not in text for text in targets)
        # The exporting account is informational, not the Persona's target identity.
        other = data.create_persona("Fictional other speaker")
        relation = data.create_relationship(other["id"], "Fictional other relationship")
        data.import_file(
            FIXTURE,
            other["id"],
            relation["id"],
            "u_demo_partner",
            "demo_source",
            confirm_human=True,
        )
        rows = data.list_messages(other["id"], relation["id"])
        assert (
            next(row for row in rows if row["source"]["source_message_id"] == "qce-demo-1")[
                "use_context"
            ]["sender_role"]
            == "owner"
        )
    finally:
        store.close()


def test_qce_header_version_counts_and_chunk_paths_fail_closed(tmp_path):
    for mutate, code in [
        (lambda d: d["metadata"].update(version="9.9.9"), "FORMAT_VERSION"),
        (lambda d: d["statistics"].update(totalMessages=99), "QCE_COUNT"),
        (lambda d: d.update(chunked={"chunksDir": "../../private", "chunks": []}), "QCE_CHUNKED"),
    ]:
        path = changed_file(tmp_path, mutate)
        with pytest.raises(DomainError) as caught:
            inspect(path)
        assert caught.value.code == code


def test_qce_group_and_temp_cannot_be_relabelled_as_private(tmp_path):
    for original, expected in [("group", "group"), ("temp", "unknown")]:
        path = changed_file(tmp_path, lambda d: d["chatInfo"].update(type=original))
        report = inspect(path, mapping={"conversation_kind": "private"})
        assert all(row["provenance"]["conversation_kind"] == expected for row in report["preview"])


def test_qce_bad_ids_seconds_and_foreign_sender_are_sanitized(tmp_path):
    def change(document):
        document["messages"][0]["timestamp"] //= 1000
        document["messages"][1]["sender"]["uid"] = "u_unrelated"
        document["messages"][2]["id"] = 123

    path = changed_file(tmp_path, change)
    report = inspect(path)
    assert report["bad_rows"] == 3 and report["total"] == 5
    assert "u_unrelated" not in json.dumps(report["errors"])


def test_qce_missing_uid_preserves_uin_without_merging_identity(tmp_path):
    path = changed_file(tmp_path, lambda d: d["messages"][0]["sender"].update(uid=""))
    report = inspect(path)
    assert report["bad_rows"] == 0
    assert report["preview"][0]["sender_id"] == "demo_partner_uin"
    assert report["preview"][0]["provenance"]["qce_sender_uid"] == ""


def test_qce_missing_peer_requires_explicit_mapping(tmp_path):
    path = changed_file(tmp_path, lambda d: d["chatInfo"].update(peerUid=None, peerUin=None))
    assert inspect(path)["bad_rows"] == 8
    assert (
        inspect(path, mapping={"qce_conversation_id": "explicit-private-thread"})["bad_rows"] == 0
    )
