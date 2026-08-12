from __future__ import annotations

import json
import hashlib
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.mail_agent.context import (
    MAX_ARTIFACTS, MAX_CONTEXT_BYTES, MAX_PRIOR_RESPONSES, MAX_THREAD_MESSAGES,
    MailContextBuilder, MailContextError,
)

NOW = "2026-07-24T00:00:00Z"


def fixture(tmp_path: Path) -> tuple[sqlite3.Connection, int, int]:
    root = tmp_path / "f"; config = FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state/foundation-ready.json", root / "state/locks/foundation.lock")
    assert FoundationTool(config).execute(FoundationRequest("init", "m406", NOW)).ready
    conn = sqlite3.connect(root / "data.db", isolation_level=None); conn.row_factory = sqlite3.Row
    conn.execute("INSERT INTO data_subjects(subject_key,created_at_utc) VALUES('s',?)", (NOW,)); subject = conn.execute("SELECT id FROM data_subjects").fetchone()[0]
    conn.execute("INSERT INTO source_revisions(provider,resource_kind,provider_object_id,revision_no,payload_hash,is_current,parsed_at_utc) VALUES('gmail','message_json','m',1,?,1,?)", ("d" * 64, NOW)); revision = conn.execute("SELECT id FROM source_revisions").fetchone()[0]
    conn.execute("INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) VALUES(?, 't', 1)", (subject,)); thread = conn.execute("SELECT id FROM mail_threads").fetchone()[0]
    conn.execute("INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role,received_at_utc,body_text,body_sha256,source_revision_id,processing_state) VALUES(?, 'm', 'inbound','user', ?, '请给我建议', ?, ?, 'queued')", (thread, NOW, "a" * 64, revision)); message = conn.execute("SELECT id FROM mail_messages").fetchone()[0]
    conn.execute("INSERT INTO mail_agent_runs(run_key,invocation_id,subject_id,request_kind,status,started_at_utc) VALUES('r','i',?,'process','started',?)", (subject,NOW)); run = conn.execute("SELECT id FROM mail_agent_runs").fetchone()[0]
    return conn, subject, run


def build(conn: sqlite3.Connection, subject: int, run: int):
    msg = conn.execute("SELECT id FROM mail_messages WHERE provider_message_id='m'").fetchone()[0]
    return MailContextBuilder(conn, shared_harness_version="shared", mail_harness_version="mail").build(run_id=run, subject_id=subject, trigger_message_id=msg, as_of_local_date="2026-07-24")


def test_recomputes_stably_has_lineage_and_is_read_only(tmp_path: Path) -> None:
    conn, subject, run = fixture(tmp_path); before = conn.total_changes
    first, second = build(conn, subject, run), build(conn, subject, run)
    assert first.canonical_json == second.canonical_json and first.sha256 == second.sha256 and first.manifest == second.manifest
    assert conn.total_changes == before and len(first.canonical_json.encode()) <= MAX_CONTEXT_BYTES
    assert first.payload["input_manifest"][0]["source_entity_id"] == first.payload["trigger_message"]["id"]
    assert first.payload["input_manifest"][0]["trust_class"] == "user_asserted"


def test_limits_order_omissions_and_prior_output_trust(tmp_path: Path) -> None:
    conn, subject, run = fixture(tmp_path); thread = conn.execute("SELECT id FROM mail_threads").fetchone()[0]
    for n in range(30):
        conn.execute("INSERT INTO source_revisions(provider,resource_kind,provider_object_id,revision_no,payload_hash,is_current) VALUES('gmail','message_json',?,1,?,1)",(f"x{n}","f"*64)); revision=conn.execute("SELECT id FROM source_revisions WHERE provider_object_id=?",(f"x{n}",)).fetchone()[0]
        conn.execute("INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role,received_at_utc,body_text,source_revision_id,processing_state) VALUES(?,?, 'inbound','user',?,?,?, 'normalized')", (thread, f"x{n}", f"2026-07-23T00:{n%60:02d}:00Z", "x" * 10000, revision))
    for n in range(7): conn.execute("INSERT INTO mail_response_artifacts(subject_id,mail_thread_id,response_kind,revision_no,generated_by_mail_agent_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,is_current,created_at_utc) VALUES(?,?, 'mail_response', ?, ?, '1','{}','old',?,0,?)", (subject,thread,n+1,run,"b"*64,f"2026-07-2{n}T00:00:00Z"))
    for n in range(10):
        conn.execute("INSERT INTO analysis_runs(run_key,subject_id,analysis_kind,status,started_at_utc) VALUES(?,?, 'daily','succeeded',?)", (f"a{n}",subject,NOW)); ar=conn.execute("SELECT id FROM analysis_runs WHERE run_key=?",(f"a{n}",)).fetchone()[0]
        conn.execute("INSERT INTO analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,generated_by_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,is_current,created_at_utc) VALUES(?, 'daily_summary', ?, ?, 1, ?, '1','{}','a',?,1,?)", (subject,f"2026-07-{n+15:02d}",f"2026-07-{n+15:02d}",ar,"c"*64,NOW))
    result = build(conn, subject, run)
    assert len(result.payload["thread_context"]) == MAX_THREAD_MESSAGES
    assert result.payload["context_limits"]["thread_body_bytes"] <= 131072
    assert len(result.payload["prior_mail_responses"]) == MAX_PRIOR_RESPONSES
    assert len(result.payload["relevant_analysis_artifacts"]) == MAX_ARTIFACTS
    assert any(x["kind"] == "thread_messages_omitted" for x in result.payload["context_limits"]["omissions"])
    assert {x.trust_class for x in result.manifest if x.input_role == "prior_mail_response"} == {"prior_model_output"}


def test_fails_closed_for_uncuttable_trigger_future_and_excludes_sensitive_expired_facts(tmp_path: Path) -> None:
    conn, subject, run = fixture(tmp_path); msg = conn.execute("SELECT id FROM mail_messages").fetchone()[0]
    conn.execute("UPDATE mail_messages SET body_text=? WHERE id=?", ("x" * 70000,msg))
    with pytest.raises(MailContextError, match="trigger_limit"): build(conn,subject,run)
    assert not conn.in_transaction and conn.execute("PRAGMA query_only").fetchone()[0] == 0
    conn.execute("UPDATE mail_messages SET body_text='ok' WHERE id=?",(msg,))
    conn.execute("INSERT INTO conversation_events(subject_id,event_type,actor_role,occurred_at_utc,mail_message_id,trust_level,created_by) VALUES(?, 'fact_source','user',?,?,'untrusted_content','mail_agent')",(subject,NOW,msg)); event=conn.execute("SELECT id FROM conversation_events").fetchone()[0]
    conn.execute("INSERT INTO user_facts(subject_id,fact_key,fact_value_json,scope,effective_from_utc,expires_at_utc,source_event_id,is_active) VALUES(?, 'gps', ?, 'temporary',NULL,NULL,?,1)", (subject,json.dumps({"latitude":1,"longitude":2,"safe":"yes"}),event))
    conn.execute("INSERT INTO user_facts(subject_id,fact_key,fact_value_json,scope,expires_at_utc,is_active) VALUES(?, 'old', '{}', 'temporary','2026-07-23T00:00:00Z',1)",(subject,))
    result = build(conn,subject,run)
    assert result.payload["active_user_facts"] == [{"id":result.payload["active_user_facts"][0]["id"],"fact_key":"gps","value":{"safe":"yes"},"scope":"temporary","effective_from_utc":None,"expires_at_utc":None,"confidence":None}]
    with pytest.raises(MailContextError, match="future"): MailContextBuilder(conn).build(run_id=run,subject_id=subject,trigger_message_id=msg,as_of_local_date="2026-07-24",requested_start_local_date="2026-07-25")


def test_selects_newest_twenty_chronologically_and_manifest_hashes_exact_fragments(tmp_path: Path) -> None:
    conn, subject, run = fixture(tmp_path); thread = conn.execute("SELECT id FROM mail_threads").fetchone()[0]; revision = conn.execute("SELECT id FROM source_revisions").fetchone()[0]
    for n in range(25):
        conn.execute("INSERT INTO source_revisions(provider,resource_kind,provider_object_id,revision_no,payload_hash,is_current) VALUES('gmail','message_json',?,1,?,1)",(f"n{n}","f"*64)); rev=conn.execute("SELECT id FROM source_revisions WHERE provider_object_id=?",(f"n{n}",)).fetchone()[0]
        conn.execute("INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role,received_at_utc,body_text,body_sha256,source_revision_id,processing_state) VALUES(?,?, 'inbound','user',?,?,?,?,'normalized')", (thread,f"n{n}",f"2026-07-23T00:00:{n:02d}Z",str(n),"e"*64,rev))
    result=build(conn,subject,run); ids=[x['provider_message_id'] for x in result.payload['thread_context']]
    assert ids == [f"n{n}" for n in range(6,25)] + ['m']
    trigger=result.payload['trigger_message']; manifest=next(x for x in result.payload['input_manifest'] if x['input_role']=='trigger_message')
    assert manifest['input_sha256']==hashlib.sha256(json.dumps(trigger,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def test_date_extension_is_controlled_and_trust_is_actor_specific(tmp_path: Path) -> None:
    conn,subject,run=fixture(tmp_path); thread=conn.execute("SELECT id FROM mail_threads").fetchone()[0]; revision=conn.execute("SELECT id FROM source_revisions").fetchone()[0]
    conn.execute("INSERT INTO source_revisions(provider,resource_kind,provider_object_id,revision_no,payload_hash,is_current) VALUES('gmail','message_json','out',1,?,1)",('f'*64,)); outrev=conn.execute("SELECT id FROM source_revisions WHERE provider_object_id='out'").fetchone()[0]
    conn.execute("INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role,received_at_utc,body_text,source_revision_id,processing_state) VALUES(?, 'out','outbound','trainlab',?,'model text',?,'normalized')",(thread,'2026-07-23T00:00:00Z',outrev))
    result=MailContextBuilder(conn).build(run_id=run,subject_id=subject,trigger_message_id=conn.execute("SELECT id FROM mail_messages WHERE provider_message_id='m'").fetchone()[0],as_of_local_date='2026-07-24',requested_start_local_date='2026-07-01',extension_reason='explicit_earlier_date')
    outbound=next(x for x in result.payload['thread_context'] if x['provider_message_id']=='out')
    assert outbound['value_origin']=='prior_model_output' and outbound['content_instruction_trust']=='untrusted_content'
    with pytest.raises(MailContextError,match='extension'): MailContextBuilder(conn).build(run_id=run,subject_id=subject,trigger_message_id=1,as_of_local_date='2026-07-24',requested_start_local_date='2026-07-01')
    with pytest.raises(MailContextError,match='extension'):
        MailContextBuilder(conn).build(
            run_id=run,
            subject_id=subject,
            trigger_message_id=1,
            as_of_local_date='2026-07-24',
            requested_start_local_date='2026-06-23',
            extension_reason='explicit_earlier_date',
        )


def test_schema_mutation_and_wrong_gmail_lineage_fail_closed(tmp_path: Path) -> None:
    conn,subject,run=fixture(tmp_path); result=build(conn,subject,run)
    bad=json.loads(result.canonical_json); bad['run']['request_kind']='poll'
    assert list(MailContextBuilder(conn).validator.iter_errors(bad))
    conn.execute("UPDATE source_revisions SET provider_object_id='other' WHERE id=(SELECT source_revision_id FROM mail_messages WHERE provider_message_id='m')")
    with pytest.raises(MailContextError,match='trigger_not_canonical'): build(conn,subject,run)


def test_schema_rejects_cross_domain_projection_field(tmp_path: Path) -> None:
    conn, subject, run = fixture(tmp_path); result = build(conn, subject, run)
    bad = json.loads(result.canonical_json)
    bad['thread_context'][0]['sport'] = 'running'
    errors = list(MailContextBuilder(conn).validator.iter_errors(bad))
    assert errors and any(list(error.path) == ['thread_context', 0] for error in errors)


def test_schema_strict_types_formats_enums_ranges_and_manifest_semantics(tmp_path: Path) -> None:
    conn, subject, run = fixture(tmp_path); result = build(conn, subject, run)
    validator = MailContextBuilder(conn).validator

    def rejects(mutator, path: list[object]) -> None:
        bad = json.loads(result.canonical_json); mutator(bad)
        assert any(list(error.path) == path for error in validator.iter_errors(bad))

    rejects(lambda value: value['trigger_message'].pop('provider_message_id'), ['trigger_message'])
    rejects(lambda value: value['run'].__setitem__('id', 'one'), ['run', 'id'])
    rejects(lambda value: value['trigger_message'].__setitem__('timestamp_utc', '2026-07-24'), ['trigger_message', 'timestamp_utc'])
    rejects(lambda value: value['trigger_message'].__setitem__('body_sha256', 'bad-hash'), ['trigger_message', 'body_sha256'])
    rejects(lambda value: value['thread_context'][0].__setitem__('direction', 'sideways'), ['thread_context', 0, 'direction'])
    rejects(lambda value: value['input_manifest'][0].__setitem__('ordinal', -1), ['input_manifest', 0, 'ordinal'])
    rejects(lambda value: value['policies'].__setitem__('extra', True), ['policies'])
    bad = json.loads(result.canonical_json)
    bad['current_health_context'] = [{
        'window': {'start': '2026/06/24', 'end': '2026-07-23'},
        'completed_days': 1,
        'source_count': 1,
        'sources': [{'id': 1, 'source_revision_id': 1, 'local_date': '2026-07-23'}],
        'aggregate_sha256': '0' * 64,
        'metrics': [],
    }]
    assert any(list(error.path) == ['current_health_context', 0, 'window', 'start'] for error in validator.iter_errors(bad))
    bad = json.loads(result.canonical_json); bad['input_manifest'][0]['input_sha256'] = '0' * 64
    with pytest.raises(MailContextError, match='fragment'): MailContextBuilder(conn, shared_harness_version='shared', mail_harness_version='mail')._validate_manifest(bad)


def test_health_context_is_a_twenty_eight_completed_day_aggregate_with_full_lineage(tmp_path: Path) -> None:
    conn, subject, run = fixture(tmp_path)
    first_day = date(2026, 6, 26)
    for offset in range(28):
        local_date = first_day + timedelta(days=offset)
        conn.execute(
            """INSERT INTO source_revisions(
                   provider,resource_kind,provider_object_id,revision_no,payload_hash,
                   is_current,parsed_at_utc
               ) VALUES('garmin','rhr',?,1,?,1,?)""",
            (str(local_date), f"{offset:064x}", NOW),
        )
        revision = conn.execute(
            "SELECT id FROM source_revisions WHERE provider='garmin' AND resource_kind='rhr' AND provider_object_id=?",
            (str(local_date),),
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO daily_health(
                   subject_id,local_date,values_json,source_revision_id,is_current
               ) VALUES(?,?,?,?,1)""",
            (
                subject,
                str(local_date),
                json.dumps({"restingHeartRate": 50 + offset % 3, "status": "BALANCED"}),
                revision,
            ),
        )

    result = build(conn, subject, run)
    assert len(result.payload["current_health_context"]) == 1
    summary = result.payload["current_health_context"][0]
    assert summary["window"] == {"start": "2026-06-26", "end": "2026-07-23"}
    assert summary["completed_days"] == 28
    assert summary["source_count"] == 28
    assert len(summary["sources"]) == 28
    assert "values" not in summary and "values_json" not in summary
    metric = next(item for item in summary["metrics"] if item["metric_key"] == "health.restingHeartRate")
    assert metric["observation_count"] == 28
    assert metric["coverage_days"] == 28
    assert metric["minimum"] == 50
    assert metric["maximum"] == 52
    health_manifest = [item for item in result.payload["input_manifest"] if item["input_role"] == "health_fact"]
    assert len(health_manifest) == 28
    assert {item["input_sha256"] for item in health_manifest} == {hashlib.sha256(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()}


def test_schema_omission_shapes_and_context_semantics_are_closed(tmp_path: Path) -> None:
    conn, subject, run = fixture(tmp_path); result = build(conn, subject, run)
    validator = MailContextBuilder(conn).validator
    bad = json.loads(result.canonical_json)
    bad['context_limits']['omissions'] = [{'kind': 'thread_body_truncated', 'entity_id': 1}]
    assert list(validator.iter_errors(bad))
    bad = json.loads(result.canonical_json)
    bad['context_limits']['omissions'] = [{'kind': 'artifact_omitted_total_limit', 'entity_id': 99, 'count': 1}]
    assert list(validator.iter_errors(bad))
    bad = json.loads(result.canonical_json); bad['context_limits']['thread_messages'] += 1
    with pytest.raises(MailContextError, match='context_limits'): MailContextBuilder._validate_context_limits(bad)
    bad = json.loads(result.canonical_json); bad['context_limits']['omissions'] = [{'kind': 'thread_body_truncated', 'entity_id': 99, 'omitted_bytes': 1, 'selection': 'oldest_body_first'}]
    with pytest.raises(MailContextError, match='omission'): MailContextBuilder._validate_context_limits(bad)


def test_manifest_is_exact_bijection_and_metadata_binding(tmp_path: Path) -> None:
    conn, subject, run = fixture(tmp_path); result = build(conn, subject, run)
    builder = MailContextBuilder(conn, shared_harness_version='shared', mail_harness_version='mail')
    for mutate, code in (
        (lambda value: value['input_manifest'].pop(), 'bijection'),
        (lambda value: value['input_manifest'].append({**value['input_manifest'][0], 'ordinal': len(value['input_manifest'])}), 'bijection'),
        (lambda value: value['input_manifest'][0].__setitem__('source_entity_type', 'activity'), 'fragment'),
        (lambda value: value['input_manifest'][0].__setitem__('trust_class', 'provider_fact'), 'fragment'),
        (lambda value: value['input_manifest'][0].__setitem__('source_revision_id', None), 'fragment'),
        (lambda value: value['input_manifest'][0].__setitem__('policy_version', 'wrong'), 'version'),
    ):
        bad = json.loads(result.canonical_json); mutate(bad)
        with pytest.raises(MailContextError, match=code): builder._validate_manifest(bad)


def test_training_plan_item_semantics_are_exact(tmp_path: Path) -> None:
    plan = {
        'id': 10, 'status': 'active', 'plan_start_local_date': '2026-07-20',
        'plan_end_local_date': '2026-07-26', 'items': [
            {'id': offset + 1, 'training_plan_id': 10, 'item_index': offset, 'local_date': f'2026-07-{20 + offset:02d}'}
            for offset in range(7)
        ],
    }
    MailContextBuilder._validate_training_plan(plan)
    for mutate, code in (
        (lambda value: value['items'][0].__setitem__('training_plan_id', 99), 'item_invalid'),
        (lambda value: value['items'][1].__setitem__('item_index', 0), 'ordinal'),
        (lambda value: value['items'][1].__setitem__('local_date', '2026-07-27'), 'item_invalid'),
    ):
        bad = json.loads(json.dumps(plan)); mutate(bad)
        with pytest.raises(MailContextError, match=code): MailContextBuilder._validate_training_plan(bad)


def test_current_collection_states_reject_even_when_manifest_hash_is_recomputed(tmp_path: Path) -> None:
    conn, subject, run = fixture(tmp_path); result = build(conn, subject, run)
    validator = MailContextBuilder(conn).validator

    def digest(value: object) -> str:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def add_manifest(payload: dict, role: str, entity_type: str, item: dict, trust: str, source_revision: int | None, entity_revision: int) -> dict:
        entry = {**payload['input_manifest'][0], 'ordinal': len(payload['input_manifest']), 'input_role': role, 'source_entity_type': entity_type, 'source_entity_id': item['id'], 'source_revision_id': source_revision, 'entity_revision': entity_revision, 'value_origin': trust, 'trust_class': trust, 'input_sha256': digest(item)}
        payload['input_manifest'].append(entry)
        return entry

    artifact = {'id': 2, 'subject_id': 1, 'artifact_kind': 'daily_summary', 'period_start_local_date': '2026-07-20', 'period_end_local_date': '2026-07-20', 'revision_no': 1, 'generated_by_run_id': 1, 'schema_version': '1', 'structured_content_json': '{}', 'user_visible_text': 'x', 'content_sha256': 'a' * 64, 'is_current': 1, 'supersedes_artifact_id': None, 'created_at_utc': NOW}
    bad = json.loads(result.canonical_json); bad['relevant_analysis_artifacts'].append(artifact); entry = add_manifest(bad, 'analysis_artifact', 'analysis_artifact', artifact, 'prior_model_output', None, 1)
    artifact['is_current'] = 0; entry['input_sha256'] = digest(artifact)
    assert any(list(error.path) == ['relevant_analysis_artifacts', 0, 'is_current'] for error in validator.iter_errors(bad))

    quality = {'id': 3, 'entity_type': 'activity', 'entity_id': 1, 'issue_code': 'x', 'severity': 'warning', 'details_json': '{}', 'status': 'open', 'first_seen_at_utc': NOW, 'last_seen_at_utc': NOW, 'resolved_at_utc': None, 'source_revision_id': None}
    bad = json.loads(result.canonical_json); bad['data_quality'].append(quality); entry = add_manifest(bad, 'quality_state', 'data_quality_issue', quality, 'derived_statistic', None, 3)
    quality['status'] = 'resolved'; entry['input_sha256'] = digest(quality)
    assert any(list(error.path) == ['data_quality', 0, 'status'] for error in validator.iter_errors(bad))

    plan = {'id': 4, 'subject_id': 1, 'analysis_artifact_id': 2, 'plan_start_local_date': '2026-07-20', 'plan_end_local_date': '2026-07-26', 'timezone': 'Asia/Hong_Kong', 'status': 'active', 'objective_json': '{}', 'constraints_json': '{}', 'created_at_utc': NOW, 'artifact_revision_no': 1, 'items': [{'id': offset + 10, 'training_plan_id': 4, 'item_index': offset, 'local_date': f'2026-07-{20 + offset:02d}', 'activity_kind': 'rest', 'prescription_json': '{}', 'rationale_text': None, 'stop_conditions_json': '{}'} for offset in range(7)]}
    bad = json.loads(result.canonical_json); bad['current_training_plan'] = plan; entry = add_manifest(bad, 'current_plan', 'training_plan', plan, 'prior_model_output', None, 1)
    plan['status'] = 'superseded'; entry['input_sha256'] = digest(plan)
    assert any(list(error.path) == ['current_training_plan'] for error in validator.iter_errors(bad))


def test_omission_selection_is_kind_specific(tmp_path: Path) -> None:
    conn, subject, run = fixture(tmp_path); result = build(conn, subject, run)
    validator = MailContextBuilder(conn).validator
    for omission in (
        {'kind': 'conversation_events_omitted', 'count': 1, 'selection': 'lowest_priority_last'},
        {'kind': 'quality_issues_omitted', 'count': 1, 'selection': 'oldest_first'},
    ):
        bad = json.loads(result.canonical_json); bad['context_limits']['omissions'] = [omission]
        assert list(validator.iter_errors(bad))


def test_sensitive_text_and_embedded_json_are_redacted_before_hashing(tmp_path: Path) -> None:
    conn, subject, run = fixture(tmp_path); message = conn.execute("SELECT id FROM mail_messages WHERE provider_message_id='m'").fetchone()[0]
    secrets = ('ya29.synthetic-token', 'GOCSPX-synthetic', 'Bearer synthetic-token', 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature', 'synthetic-code', 'synthetic-state', '1.352100, 103.819800')
    conn.execute("UPDATE mail_messages SET body_text=? WHERE id=?", (f"普通文本 {secrets[0]} {secrets[1]} {secrets[2]} {secrets[3]} https://example.test/callback?code={secrets[4]}&state={secrets[5]} {secrets[6]}", message))
    conn.execute("INSERT INTO conversation_events(subject_id,event_type,actor_role,occurred_at_utc,mail_message_id,structured_payload_json,trust_level,created_by) VALUES(?, 'nested', 'user', ?, ?, ?, 'untrusted_content', 'test')", (subject, NOW, message, json.dumps({'note': f'{secrets[2]} {secrets[6]}', 'client_secret': 'synthetic-secret'})))
    conn.execute("INSERT INTO data_quality_issues(entity_type,entity_id,issue_code,severity,details_json,status,first_seen_at_utc,last_seen_at_utc) VALUES('mail_message',?,'nested','warning',?,'open',?,?)", (message, json.dumps({'note': f'https://example.test/?access_token={secrets[0]}', 'refresh_token': 'synthetic-refresh', 'coordinate': secrets[6]}), NOW, NOW))
    result = build(conn, subject, run)
    for secret in secrets:
        assert secret not in result.canonical_json and secret not in result.sha256
    assert '<redacted-secret>' in result.canonical_json and '<redacted-precise-location>' in result.canonical_json
    event = result.payload['conversation_events'][0]
    assert json.loads(event['structured_payload_json']) == {'note': 'Bearer <redacted-secret> <redacted-precise-location>'}
    quality = result.payload['data_quality'][0]
    assert json.loads(quality['details_json']) == {'coordinate': '<redacted-precise-location>', 'note': 'https://example.test/?access_token=<redacted-secret>'}
    with pytest.raises(MailContextError) as error: __import__('trainlab.mail_agent.context', fromlist=['_safe'])._safe({'details_json': 'not-json ya29.synthetic-token'})
    assert all(secret not in str(error.value) for secret in secrets)


def test_context_read_authorizer_denies_raw_attachment_and_sample_tables(tmp_path: Path) -> None:
    conn, subject, run = fixture(tmp_path); forbidden = {'raw_objects', 'mail_attachments', 'activity_samples'}; reads: set[str] = set()

    def authorizer(action: int, first: str | None, second: str | None, database: str | None, source: str | None) -> int:
        if action == sqlite3.SQLITE_READ and first:
            reads.add(first)
            if first in forbidden: return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(authorizer)
    try:
        build(conn, subject, run)
    finally:
        conn.set_authorizer(None)
    assert not reads.intersection(forbidden)


def test_nested_projection_mutation_is_rejected(tmp_path: Path) -> None:
    conn,subject,run=fixture(tmp_path); result=build(conn,subject,run)
    bad=json.loads(result.canonical_json); bad['thread_context'][0]['raw_gmail_json']={'token':'no'}
    with pytest.raises(MailContextError,match='nested_schema'): MailContextBuilder._validate_nested(bad)


def test_partial_generator_response_remains_prior_context(tmp_path: Path) -> None:
    conn,subject,run=fixture(tmp_path); thread=conn.execute("SELECT id FROM mail_threads").fetchone()[0]
    conn.execute("INSERT INTO mail_agent_runs(run_key,invocation_id,subject_id,request_kind,status,started_at_utc) VALUES('partial','partial',?,'process','partial',?)",(subject,NOW)); partial=conn.execute("SELECT id FROM mail_agent_runs WHERE run_key='partial'").fetchone()[0]
    conn.execute("INSERT INTO mail_response_artifacts(subject_id,mail_thread_id,response_kind,revision_no,generated_by_mail_agent_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,is_current,created_at_utc) VALUES(?,?,'mail_response',1,?,'1','{}','published',?,1,?)",(subject,thread,partial,'a'*64,NOW))
    result=build(conn,subject,run)
    assert result.payload['prior_mail_responses'][0]['generated_by_mail_agent_run_id']==partial


def test_real_over_one_mib_artifacts_are_trimmed_with_manifest_and_counts(tmp_path: Path) -> None:
    conn,subject,run=fixture(tmp_path)
    for n in range(8):
        conn.execute("INSERT INTO analysis_runs(run_key,subject_id,analysis_kind,status,started_at_utc) VALUES(?,?, 'daily','succeeded',?)",(f'huge{n}',subject,NOW)); ar=conn.execute("SELECT id FROM analysis_runs WHERE run_key=?",(f'huge{n}',)).fetchone()[0]
        day=f'2026-07-{17+n:02d}'
        conn.execute("INSERT INTO analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,generated_by_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,is_current,created_at_utc) VALUES(?, 'daily_summary',?,?,1,?,'1',? ,?, ?,1,?)",(subject,day,day,ar,json.dumps({'large':'x'*140000}),'y'*140000,'a'*64,NOW))
    result=build(conn,subject,run)
    assert len(result.canonical_json.encode())<=1_000_000
    assert result.payload['context_limits']['related_artifacts']==len(result.payload['relevant_analysis_artifacts'])
    assert any(x['kind']=='artifact_omitted_total_limit' for x in result.payload['context_limits']['omissions'])
    for entry in result.payload['input_manifest']:
        assert entry['ordinal'] < len(result.payload['input_manifest'])


def test_uncuttable_active_fact_core_fails_closed(tmp_path: Path) -> None:
    conn,subject,run=fixture(tmp_path); msg=conn.execute("SELECT id FROM mail_messages WHERE provider_message_id='m'").fetchone()[0]
    conn.execute("INSERT INTO conversation_events(subject_id,event_type,actor_role,occurred_at_utc,mail_message_id,trust_level,created_by) VALUES(?, 'source_core','user',?,?,'untrusted_content','mail_agent')",(subject,NOW,msg)); event=conn.execute("SELECT id FROM conversation_events WHERE event_type='source_core'").fetchone()[0]
    for n in range(100): conn.execute("INSERT INTO user_facts(subject_id,fact_key,fact_value_json,scope,source_event_id,is_active) VALUES(?,?,?,'temporary',?,1)",(subject,f'core{n}',json.dumps({'v':'z'*16000}),event))
    with pytest.raises(MailContextError,match='uncuttable_core'): build(conn,subject,run)
