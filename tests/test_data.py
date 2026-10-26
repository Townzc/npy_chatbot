import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from chattwin.domain import DomainError
from chattwin.importers import DataService
from chattwin.importers.parsers import digest, inspect, parse, parse_time
from chattwin.storage import Store, imports, messages

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def service(tmp_path):
    store = Store(tmp_path / "private")
    store.migrate()
    yield DataService(store)
    store.close()


def scope(service):
    persona = service.create_persona("虚构本人")
    relationship = service.create_relationship(persona["id"], "虚构关系")
    return persona["id"], relationship["id"]


def imported(
    service,
    filename="chatlab_wechat.synthetic.jsonl",
    owner="demo_owner",
    account="demo_source_account",
    human=True,
):
    p, r = scope(service)
    report = service.import_file(
        EXAMPLES / filename,
        p,
        r,
        owner,
        account,
        confirm_human=human,
        mapping={"conversation_kind": "private"} if filename.startswith("canonical") else None,
    )
    return p, r, report


def test_chatlab_seconds_origin_and_repeat(service):
    p, r, report = imported(service)
    items = service.list_messages(p, r)
    assert report["inserted"] == 4
    assert items[0]["occurred_at"].startswith("2026-10-26")
    assert items[0]["origin"] == "unknown"
    assert items[1]["origin"] == "human"
    assert items[1]["sender_id"] == "demo_owner"
    again = service.import_file(
        EXAMPLES / "chatlab_wechat.synthetic.jsonl",
        p,
        r,
        "demo_owner",
        "demo_source_account",
        confirm_human=True,
    )
    assert again["inserted"] == 0 and again["duplicates"] == 4
    assert len(service.store.rows(messages)) == 4


def test_exporter_is_not_target_and_unknown_cannot_train(service):
    p, r, _ = imported(
        service, "chatlab_qq.synthetic.json", "demo_qq_friend", "source-qq", human=False
    )
    with pytest.raises(DomainError, match="Confirm human origin"):
        service.build_dataset(p, r)
    service.import_file(
        EXAMPLES / "chatlab_qq.synthetic.json",
        p,
        r,
        "demo_qq_friend",
        "source-qq",
        confirm_human=True,
    )
    rows = service.list_messages(p, r)
    assert rows[0]["use_context"]["sender_role"] == "owner"
    assert rows[1]["use_context"]["sender_role"] == "partner"
    assert rows[1]["use_context"]["use_policy"]["training_target"] is False


def test_canonical_use_context_untrusted_and_roundtrip(service, tmp_path):
    p, r, _ = imported(service, "canonical_messages.synthetic.jsonl", human=False)
    assert all(
        not row["use_context"]["use_policy"]["training_target"]
        for row in service.list_messages(p, r)
    )
    service.import_file(
        EXAMPLES / "canonical_messages.synthetic.jsonl",
        p,
        r,
        "demo_owner",
        "demo_source_account",
        confirm_human=True,
        mapping={"conversation_kind": "private"},
    )
    destination = tmp_path / "export.jsonl"
    manifest = service.export_canonical(p, r, destination)
    assert manifest["count"] == 4
    inspected = inspect(destination)
    assert inspected["bad_rows"] == 0 and inspected["total"] == 4
    assert all(row[1].use_context is None for row in parse(destination))


def test_bad_jsonl_rolls_back_and_explicit_skip(service, tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text((EXAMPLES / "chatlab_wechat.synthetic.jsonl").read_text() + "{not-json}\n")
    p, r = scope(service)
    assert inspect(path)["bad_rows"] == 1
    with pytest.raises(DomainError):
        service.import_file(path, p, r, "demo_owner", "account")
    assert not service.store.rows(imports)
    assert not service.store.rows(messages)
    report = service.import_file(path, p, r, "demo_owner", "account", skip_errors=True)
    assert report["skipped"] == 1 and report["inserted"] == 4


def test_null_unknown_type_reply_and_group_exclusion(service, tmp_path):
    document = json.loads((EXAMPLES / "chatlab_qq.synthetic.json").read_text())
    document["meta"]["type"] = "group"
    document["messages"].append(
        {
            "sender": "demo_qq_owner",
            "timestamp": 1792972822,
            "type": 777,
            "content": None,
            "replyToMessageId": "missing",
        }
    )
    path = tmp_path / "group.json"
    path.write_text(json.dumps(document))
    preview = inspect(path)
    assert preview["types"]["unsupported"] == 1
    assert preview["unresolved_references"] == 1
    p, r = scope(service)
    report = service.import_file(path, p, r, "demo_qq_owner", "qq", confirm_human=True)
    assert report["candidate_training_targets"] == 0
    assert len(service.store.rows(messages)) == 3
    assert service.list_messages(p, r) == []


def test_csv_mapping_bom_newline_and_repeat_text(service, tmp_path):
    path = tmp_path / "custom.csv"
    path.write_text(
        '\ufeffconv,who,when,body\nc,p,2026-10-26T00:00:00Z,"你好\n世界"\nc,o,2026-10-26T00:00:01Z,好\nc,o,2026-10-26T00:00:01Z,好\n'
    )
    p, r = scope(service)
    mapping = {"fields": {"conversation": "conv", "sender": "who", "time": "when", "text": "body"}}
    report = service.import_file(path, p, r, "o", "a", mapping=mapping, confirm_human=True)
    assert report["inserted"] == 3
    assert service.list_messages(p, r)[0]["content"]["text"] == "你好\n世界"
    assert report["stable_id_coverage"] == 0
    assert service.build_dataset(p, r)["counts"]["train"] == 1


def test_time_units_and_dst():
    with pytest.raises(ValueError):
        parse_time(1792972800000, unit="seconds")
    assert parse_time(1792972800000, unit="milliseconds") == parse_time(1792972800, unit="seconds")
    with pytest.raises(ValueError):
        parse_time("2026-11-01T01:30:00", "America/Los_Angeles")
    with pytest.raises(ValueError):
        parse_time("2026-03-08T02:30:00", "America/Los_Angeles")


def test_memory_scope_confirmation_correction_and_delete(service):
    p, r, _ = imported(service)
    p2, r2, _ = imported(service)
    message_id = service.list_messages(p, r)[0]["id"]
    item = service.add_memory(p, r, "喜欢安静的展览", [message_id])
    assert service.retrieve_memories(p, r, "展览") == []
    service.update_memory(item["id"], p, r, confirmed=True)
    assert len(service.retrieve_memories(p, r, "展览")) == 1
    assert service.retrieve_memories(p2, r2, "展览") == []
    with pytest.raises(DomainError):
        service.add_memory(p, r2, "bad scope", [message_id])
    service.update_memory(item["id"], p, r, text="喜欢热闹的展览")
    assert service.retrieve_memories(p, r, "展览") == []
    service.update_memory(item["id"], p, r, confirmed=True, deleted=True)
    assert service.retrieve_memories(p, r, "展览") == []


def test_same_names_do_not_merge_and_remap_refused(service, tmp_path):
    doc = json.loads((EXAMPLES / "chatlab_qq.synthetic.json").read_text())
    for message in doc["messages"]:
        message["accountName"] = "same name"
    path = tmp_path / "names.json"
    path.write_text(json.dumps(doc))
    assert len(inspect(path)["senders"]) == 2
    p, r = scope(service)
    service.import_file(path, p, r, "demo_qq_owner", "qq")
    second = service.create_relationship(p, "other")
    with pytest.raises(DomainError, match="different relationship"):
        service.import_file(path, p, second["id"], "demo_qq_owner", "qq")


def test_dataset_freeze_split_and_retrieval_holdout(service, tmp_path):
    path = tmp_path / "sessions.csv"
    rows = ["conversation,sender_id,occurred_at,text,message_id"]
    base = datetime(2026, 1, 1, tzinfo=UTC)
    questions = ["吃饭", "天气", "爬山", "咖啡", "旅行", "电影", "音乐", "跑步", "小说", "比赛"]
    answers = ["吃面条", "晴朗", "去高山", "拿铁", "海边", "喜剧", "爵士", "五公里", "科幻", "篮球"]
    for index, (question, answer) in enumerate(zip(questions, answers, strict=True)):
        date = base + timedelta(days=index)
        rows += [
            f"conv,friend,{date.isoformat()},{question},q{index}",
            f"conv,owner,{(date + timedelta(seconds=30)).isoformat()},{answer},a{index}",
        ]
    path.write_text("\n".join(rows))
    p, r = scope(service)
    service.import_file(path, p, r, "owner", "account", confirm_human=True)
    manifest = service.build_dataset(p, r)
    directory = Path(manifest["path"])
    disk = json.loads((directory / "manifest.json").read_text())
    assert (
        digest({key: value for key, value in disk.items() if key != "dataset_hash"})
        == disk["dataset_hash"]
    )
    assert manifest["counts"]["validation"] and manifest["counts"]["test"]
    split_ids = {}
    for split in ("train", "validation", "test"):
        examples = [
            json.loads(line) for line in (directory / f"{split}.jsonl").read_text().splitlines()
        ]
        split_ids[split] = {id for example in examples for id in example["source_message_ids"]}
        for example in examples:
            assert example["target_index"] == len(example["messages"]) - 1
            assert example["messages"][-1]["role"] == "assistant"
    assert not split_ids["train"] & split_ids["test"]
    assert not split_ids["train"] & split_ids["validation"]
    assert not split_ids["validation"] & split_ids["test"]
    style = service.build_style(p, r)
    assert not set(style["source_message_ids"]) & split_ids["test"]
    held_out = next(iter(split_ids["test"]))
    service.add_memory(p, r, "测试秘密", [held_out], confirmed=True)
    assert service.retrieve_memories(p, r, "测试秘密") == []
    future = service.build_style(p, r, before=base)
    assert future["count"] == 0


def test_canonical_missing_conversation_kind_never_grants_private_use(service):
    p, r = scope(service)
    report = service.import_file(
        EXAMPLES / "canonical_messages.synthetic.jsonl",
        p,
        r,
        "demo_owner",
        "demo_source_account",
        confirm_human=True,
    )
    assert report["inserted"] == 4
    assert report["candidate_training_targets"] == 0
    assert service.list_messages(p, r) == []
    assert all(
        row["payload"]["provenance"]["conversation_kind"] == "unknown"
        for row in service.store.rows(messages)
    )


def test_canonical_inspect_discloses_account_without_trusting_ui_default(service):
    report = service.inspect(
        EXAMPLES / "canonical_messages.synthetic.jsonl", mapping={"source_account_id": "preview"}
    )
    assert report["total"] == 4 and report["bad_rows"] == 0
    assert {sender["source_account_id"] for sender in report["senders"]} == {"demo_source_account"}
    p, r = scope(service)
    with pytest.raises(DomainError):
        service.import_file(
            EXAMPLES / "canonical_messages.synthetic.jsonl",
            p,
            r,
            "demo_owner",
            "wrong-account",
            mapping={"_inspect": True, "conversation_kind": "private"},
            confirm_human=True,
        )
    assert service.store.rows(messages) == []
