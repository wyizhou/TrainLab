"""Offline L2-11 FIT transport and parser acceptance."""
from __future__ import annotations

import io
import hashlib
import json
import sqlite3
import stat
import struct
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import fitdecode
import pytest
from fitdecode.utils import compute_crc

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.garmin import SyncRequest
from trainlab.garmin import GarminCollectionTool, GarminConfig, GarminError


def _tool(tmp_path: Path) -> GarminCollectionTool:
    return GarminCollectionTool(GarminConfig(tmp_path / "db", tmp_path / "raw", tmp_path / "state", "2026-01-01"))


def _session(path: Path) -> tuple[str, str]:
    with fitdecode.FitReader(path, check_crc=True) as reader:
        for frame in reader:
            if isinstance(frame, fitdecode.FitDataMessage) and frame.name == "session":
                fields = {field.name: field.value for field in frame.fields}
                stamp = fields["start_time"].isoformat().replace("+00:00", "Z")
                return stamp, str(fields["sport"])
    raise AssertionError("fixture lacks session")


def _original_zip(fit: bytes) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("activity.fit", fit)
    return payload.getvalue()


def _zip_payload(entries: list[tuple[str, bytes]]) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return payload.getvalue()


def _valid_fit_variant(fit: bytes, position: int = 1000) -> bytes:
    """Change a record value while preserving FIT structure and footer CRC."""
    assert 14 <= position < len(fit) - 2
    variant = bytearray(fit)
    variant[position] ^= 1
    variant[-2:] = struct.pack("<H", compute_crc(variant[:-2]))
    # Prove the test seam produced a genuinely parseable, different FIT.
    with fitdecode.FitReader(bytes(variant), check_crc=True) as reader:
        assert any(isinstance(frame, fitdecode.FitDataMessage) for frame in reader)
    return bytes(variant)


def _minimal_fit_without_session() -> bytes:
    header = bytearray(struct.pack("<BBHI4s", 14, 0x10, 0, 0, b".FIT"))
    header += struct.pack("<H", compute_crc(header))
    return bytes(header + struct.pack("<H", compute_crc(header)))


class _ActivityTransport:
    def __init__(self, payload: bytes, start: str, type_key: str = "running"):
        self.payload = payload
        self.start = start
        self.type_key = type_key

    def login(self): pass
    def identity(self): return "l2-11-candidate-matrix"
    def fetch_health(self, *_args): return []
    def fetch_range(self, *_args): return []
    def fetch_account(self, *_args): return []
    def list_activities(self, *_args): return [{"activityId": 1, "startTimeGMT": self.start}]
    def activity_summary(self, _id):
        return {
            "activityId": 1,
            "activityName": "fixture",
            "activityType": {"typeKey": self.type_key},
            "startTimeGMT": self.start,
            "duration": 1,
        }
    def activity_original(self, _id): return self.payload


def _activity_pipeline(
    tmp_path: Path,
    payload: bytes,
    *,
    fixture: str = "Running.fit",
    type_key: str = "running",
) -> tuple[GarminCollectionTool, _ActivityTransport, FoundationConfig]:
    sample = Path(__file__).resolve().parents[1] / "test_data" / "new" / fixture
    start, _sport = _session(sample)
    root = tmp_path / "data"
    foundation = FoundationConfig(
        root, root / "data.db", root / "raw", root / "state",
        root / "state/ready", root / "state/locks/f.lock",
    )
    assert FoundationTool(foundation).execute(
        FoundationRequest("init", "l2-11", "2026-01-01T00:00:00Z")
    ).status == "initialized"
    transport = _ActivityTransport(payload, start, type_key)
    tool = GarminCollectionTool(
        GarminConfig(
            foundation.database_path, foundation.raw_root,
            foundation.state_root, "2026-01-01", request_min_interval_ms=0,
        ),
        transport,
        sleep=lambda _: None,
        clock=lambda: datetime(2026, 7, 20),
    )
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    return tool, transport, foundation


def _full(tool: GarminCollectionTool, invocation: str):
    return tool.execute(
        SyncRequest(
            "full",
            through_local_date="2026-07-19",
            invocation_id=invocation,
        )
    )


def test_six_representative_fits_pass_crc_and_session_identity_without_temp_residue(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    samples = sorted((Path(__file__).resolve().parents[1] / "test_data" / "new").glob("*.fit"))
    assert len(samples) == 6
    for sample in samples:
        start, sport = _session(sample)
        assert tool._fit_session_identity(sample.read_bytes(), start, sport) == (start, sport)
    assert not list(tmp_path.glob(".fit-download-*"))


def test_session_identity_time_and_sport_mismatch_are_rejected(tmp_path: Path) -> None:
    tool = _tool(tmp_path); sample = Path(__file__).resolve().parents[1] / "test_data" / "new" / "Running.fit"
    start, _sport = _session(sample)
    with pytest.raises(GarminError, match="fit_identity_mismatch"):
        tool._fit_session_identity(sample.read_bytes(), "2020-01-01T00:00:00Z", "running")
    with pytest.raises(GarminError, match="fit_identity_mismatch"):
        tool._fit_session_identity(sample.read_bytes(), start, "cycling")
    assert not list(tmp_path.glob(".fit-download-*"))


def test_multi_session_identity_uses_earliest_start_and_fit_activity_semantics(
    tmp_path: Path,
) -> None:
    tool = _tool(tmp_path)
    start = datetime.fromisoformat("2026-07-18T22:53:01+00:00")
    later = datetime.fromisoformat("2026-07-18T23:03:01+00:00")
    homogeneous = [
        {"start_time": later, "sport": "running", "sub_sport": "generic"},
        {"start_time": start, "sport": "running", "sub_sport": "generic"},
    ]
    assert tool._validate_fit_sessions(
        homogeneous, [{"type": "manual", "num_sessions": 2}],
        "2026-07-18T22:53:01Z", "running",
    ) == ("2026-07-18T22:53:01Z", "running")

    multisport = [
        {"start_time": start, "sport": "running", "sub_sport": "generic"},
        {"start_time": later, "sport": "cycling", "sub_sport": "generic"},
    ]
    assert tool._validate_fit_sessions(
        multisport, [{"type": "auto_multi_sport", "num_sessions": 2}],
        "2026-07-18T22:53:01Z", "multisport",
    ) == ("2026-07-18T22:53:01Z", "running")
    with pytest.raises(GarminError, match="fit_ambiguous_session"):
        tool._validate_fit_sessions(
            multisport, [{"type": "manual", "num_sessions": 2}],
            "2026-07-18T22:53:01Z", "running",
        )
    with pytest.raises(GarminError, match="fit_ambiguous_session"):
        tool._validate_fit_sessions(
            homogeneous, [{"type": "manual", "num_sessions": 3}],
            "2026-07-18T22:53:01Z", "running",
        )
    with pytest.raises(GarminError, match="fit_identity_mismatch"):
        tool._validate_fit_sessions(
            homogeneous, [{"type": "manual", "num_sessions": 2}],
            "2026-07-18T20:00:00Z", "running",
        )


def test_ordered_multi_session_evidence_and_current_revision_are_explicit(
    tmp_path: Path,
) -> None:
    fit = (Path(__file__).resolve().parents[1] / "test_data" / "new" / "Running.fit").read_bytes()
    tool, _transport, foundation = _activity_pipeline(tmp_path, fit)
    assert _full(tool, "session-evidence").status == "succeeded"

    def field(name, value, units, number):
        return SimpleNamespace(
            name=name, value=value, units=units, def_num=number,
            field_type="field", field_def=None,
        )

    with tool.repo.connect() as conn:
        activity, revision = conn.execute(
            """SELECT activity_source_revisions.activity_id,
                      activity_source_revisions.source_revision_id
               FROM activity_source_revisions
               WHERE source_role='activity_fit' AND is_active=1"""
        ).fetchone()
        tool._store_fit_session_evidence(
            conn, int(activity), int(revision), [
                field("start_time", datetime.fromisoformat("2026-07-18T23:03:01+00:00"), None, 2),
                field("sport", "cycling", None, 5),
            ],
        )
    with sqlite3.connect(foundation.database_path) as conn:
        extras_raw, source_map_raw = conn.execute(
            "SELECT extras_json,source_map_json FROM activities"
        ).fetchone()
        extras, source_map = json.loads(extras_raw), json.loads(source_map_raw)
        assert [entry["session_index"] for entry in extras["fit_sessions"]] == [0, 1]
        assert [entry["source_revision_id"] for entry in extras["fit_sessions"]] == [revision, revision]
        assert extras["fit_sessions"][0]["fields"]["sport"]["value"] == "running"
        assert extras["fit_sessions"][1]["fields"]["sport"]["value"] == "cycling"
        assert source_map["fit_sessions"] == {
            "source_revision_id": revision,
            "source_kind": "fit_session",
            "ordered": True,
            "session_count": 2,
        }


def test_zip_slip_crc_and_multiple_candidate_boundaries_leave_no_temp_residue(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    sample = next((Path(__file__).resolve().parents[1] / "test_data" / "new").glob("*.fit")).read_bytes()
    slipped = io.BytesIO()
    with zipfile.ZipFile(slipped, "w") as archive:
        archive.writestr("../escape.fit", sample)
    with pytest.raises(GarminError, match="fit_zip_unsafe_member"):
        tool._extract_fit_candidates(slipped.getvalue())
    multi = io.BytesIO()
    with zipfile.ZipFile(multi, "w") as archive:
        archive.writestr("one.fit", sample)
        archive.writestr("two.fit", sample)
    assert len(tool._extract_fit_candidates(multi.getvalue())) == 2
    assert not list(tmp_path.glob(".fit-download-*"))


@pytest.mark.parametrize("name", ["/absolute.fit", "C:\\escape.fit", "../parent.fit"])
def test_unsafe_member_names_are_rejected_and_cleaned(tmp_path: Path, name: str) -> None:
    tool = _tool(tmp_path); payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive: archive.writestr(name, b"x" * 12)
    with pytest.raises(GarminError): tool._extract_fit_candidates(payload.getvalue())
    assert not list(tmp_path.glob(".fit-download-*"))


def test_corrupt_and_no_fit_containers_clean_up(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    with pytest.raises(GarminError): tool._extract_fit_candidates(b"PK\x03\x04broken")
    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w") as archive: archive.writestr("note.txt", b"safe")
    assert tool._extract_fit_candidates(empty.getvalue()) == []
    assert not list(tmp_path.glob(".fit-download-*"))


def test_fit_extractor_direct_zip_crc_and_no_fit_matrix(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    fit = (Path(__file__).resolve().parents[1] / "test_data" / "new" / "Running.fit").read_bytes()
    assert tool._extract_fit_candidates(fit) == [fit]
    assert tool._extract_fit_candidates(_zip_payload([("readme.txt", b"none")])) == []
    assert tool._extract_fit_candidates(_zip_payload([("activity.FIT", fit)])) == [fit]

    corrupt = bytearray(_zip_payload([("activity.fit", fit)]))
    member_offset = bytes(corrupt).find(fit)
    assert member_offset >= 0
    corrupt[member_offset + 1000] ^= 1
    with pytest.raises(GarminError, match="fit_zip_invalid"):
        tool._extract_fit_candidates(bytes(corrupt))
    with pytest.raises(GarminError, match="fit_zip_invalid"):
        tool._extract_fit_candidates(b"PK\x03\x04truncated")
    assert not list(tmp_path.glob(".fit-download-*"))


def test_fit_extractor_size_and_member_count_boundaries_use_limits_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool(tmp_path)
    monkeypatch.setattr(tool, "_FIT_MAX_BYTES", 64)
    monkeypatch.setattr(tool, "_FIT_MAX_MEMBERS", 2)
    monkeypatch.setattr(tool, "_FIT_MAX_TOTAL_BYTES", 80)

    direct = b"F" * 64
    assert tool._extract_fit_candidates(direct) == [direct]
    with pytest.raises(GarminError, match="fit_zip_limits_exceeded"):
        tool._extract_fit_candidates(direct + b"x")

    # Container overhead is larger than the per-member limit, so temporarily
    # separate the response limit from member/total uncompressed limits.
    monkeypatch.setattr(tool, "_FIT_MAX_BYTES", 1024)
    exact_members = _zip_payload([("one.txt", b"x"), ("two.txt", b"y")])
    assert tool._extract_fit_candidates(exact_members) == []
    with pytest.raises(GarminError, match="fit_zip_limits_exceeded"):
        tool._extract_fit_candidates(
            _zip_payload([("one.txt", b"x"), ("two.txt", b"y"), ("three.txt", b"z")])
        )

    monkeypatch.setattr(tool, "_FIT_MAX_BYTES", 256)
    monkeypatch.setattr(tool, "_FIT_MAX_TOTAL_BYTES", 512)
    compressed = io.BytesIO()
    with zipfile.ZipFile(compressed, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("activity.fit", b"x" * 256)
    assert len(compressed.getvalue()) < 256
    assert tool._extract_fit_candidates(compressed.getvalue()) == [b"x" * 256]
    oversized = io.BytesIO()
    with zipfile.ZipFile(oversized, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("activity.fit", b"x" * 257)
    with pytest.raises(GarminError, match="fit_zip_limits_exceeded"):
        tool._extract_fit_candidates(oversized.getvalue())

    monkeypatch.setattr(tool, "_FIT_MAX_TOTAL_BYTES", 64)
    total_exact = io.BytesIO()
    with zipfile.ZipFile(total_exact, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("one.fit", b"x" * 32)
        archive.writestr("two.fit", b"y" * 32)
    assert tool._extract_fit_candidates(total_exact.getvalue()) == [b"x" * 32, b"y" * 32]
    total_oversized = io.BytesIO()
    with zipfile.ZipFile(total_oversized, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("one.fit", b"x" * 32)
        archive.writestr("two.fit", b"y" * 33)
    with pytest.raises(GarminError, match="fit_zip_limits_exceeded"):
        tool._extract_fit_candidates(total_oversized.getvalue())
    assert not list(tmp_path.glob(".fit-download-*"))


def test_fit_extractor_rejects_paths_links_and_special_files_but_accepts_directories(
    tmp_path: Path,
) -> None:
    tool = _tool(tmp_path)
    fit = b"x" * 12
    safe = io.BytesIO()
    with zipfile.ZipFile(safe, "w") as archive:
        archive.writestr("nested/", b"")
        ordinary = zipfile.ZipInfo("nested/activity.fit")
        ordinary.create_system = 0
        ordinary.external_attr = 0x20
        archive.writestr(ordinary, fit)
    assert tool._extract_fit_candidates(safe.getvalue()) == [fit]

    for name in ("/absolute.fit", "../parent.fit", "folder/../../escape.fit", "C:\\escape.fit"):
        with pytest.raises(GarminError, match="fit_zip_unsafe_member"):
            tool._extract_fit_candidates(_zip_payload([(name, fit)]))
    for mode in (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600, stat.S_IFCHR | 0o600):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            info = zipfile.ZipInfo("special.fit")
            info.create_system = 3
            info.external_attr = mode << 16
            archive.writestr(info, fit)
        with pytest.raises(GarminError, match="fit_zip_unsafe_member"):
            tool._extract_fit_candidates(payload.getvalue())
    assert not list(tmp_path.glob(".fit-download-*"))


def test_fit_extractor_encrypted_or_runtime_read_failure_is_zip_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool(tmp_path)
    payload = _zip_payload([("activity.fit", b"x" * 12)])
    original = zipfile.ZipFile.read

    def encrypted_read(self, *args, **kwargs):
        raise RuntimeError("encrypted member requires password")

    monkeypatch.setattr(zipfile.ZipFile, "read", encrypted_read)
    with pytest.raises(GarminError, match="fit_zip_invalid"):
        tool._extract_fit_candidates(payload)
    monkeypatch.setattr(zipfile.ZipFile, "read", original)
    assert not list(tmp_path.glob(".fit-download-*"))


def test_member_count_and_duplicate_candidates_are_bounded_and_cleaned(tmp_path: Path) -> None:
    tool = _tool(tmp_path); many = io.BytesIO()
    with zipfile.ZipFile(many, "w") as archive:
        for index in range(tool._FIT_MAX_MEMBERS + 1): archive.writestr(f"{index}.txt", b"x")
    with pytest.raises(GarminError, match="fit_zip_limits_exceeded"):
        tool._extract_fit_candidates(many.getvalue())
    assert not list(tmp_path.glob(".fit-download-*"))


def test_safe_directory_is_skipped_but_symlink_member_is_rejected(tmp_path: Path) -> None:
    tool = _tool(tmp_path); safe = io.BytesIO()
    with zipfile.ZipFile(safe, "w") as archive:
        archive.writestr("folder/", b""); archive.writestr("folder/activity.fit", b"x" * 12)
    assert tool._extract_fit_candidates(safe.getvalue()) == [b"x" * 12]
    link = io.BytesIO()
    with zipfile.ZipFile(link, "w") as archive:
        info = zipfile.ZipInfo("linked.fit"); info.external_attr = (0o120777 << 16); archive.writestr(info, b"x" * 12)
    with pytest.raises(GarminError, match="fit_zip_unsafe_member"):
        tool._extract_fit_candidates(link.getvalue())
    assert not list(tmp_path.glob(".fit-download-*"))


def test_duplicate_same_hash_and_valid_plus_crc_invalid_publish_one_canonical_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fit = (Path(__file__).resolve().parents[1] / "test_data" / "new" / "Running.fit").read_bytes()
    invalid = bytearray(fit)
    invalid[1000] ^= 1
    payload = _zip_payload([
        ("duplicate-a.fit", fit),
        ("invalid.fit", bytes(invalid)),
        ("duplicate-b.fit", fit),
    ])
    tool, _transport, foundation = _activity_pipeline(tmp_path, payload)
    checked: list[str] = []
    original_identity = tool._fit_session_identity

    def counted_identity(candidate: bytes, start: str, sport: str):
        checked.append(hashlib.sha256(candidate).hexdigest())
        return original_identity(candidate, start, sport)

    monkeypatch.setattr(tool, "_fit_session_identity", counted_identity)
    receipt = _full(tool, "candidate-dedup")
    assert receipt.status == "succeeded"
    assert len(checked) == 2
    assert len(set(checked)) == 2
    with sqlite3.connect(foundation.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM raw_objects WHERE resource_kind='activity_fit'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM source_revisions WHERE resource_kind='activity_fit' AND is_current=1"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM raw_objects WHERE relative_path LIKE '%.zip'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM data_quality_issues WHERE issue_code='ambiguous_activity_fit'"
        ).fetchone()[0] == 0
    assert not list((tmp_path / "data").glob(".fit-download-*"))
    assert not list((tmp_path / "data").rglob("original.zip"))


def test_all_invalid_candidate_error_priority_is_stable_across_zip_order(
    tmp_path: Path,
) -> None:
    fit = (Path(__file__).resolve().parents[1] / "test_data" / "new" / "Running.fit").read_bytes()
    corrupt = bytearray(fit)
    corrupt[1000] ^= 1
    no_session = _minimal_fit_without_session()
    tool, transport, foundation = _activity_pipeline(
        tmp_path,
        _zip_payload([("no-session.fit", no_session), ("crc.fit", bytes(corrupt))]),
    )
    first = _full(tool, "invalid-order-a")
    assert first.status == "partial"
    transport.payload = _zip_payload([("crc.fit", bytes(corrupt)), ("no-session.fit", no_session)])
    second = _full(tool, "invalid-order-b")
    assert second.status == "partial"
    with sqlite3.connect(foundation.database_path) as conn:
        codes = [
            row[0] for row in conn.execute(
                """SELECT error_code FROM garmin_sync_items
                   WHERE resource_kind='activity_fit' AND stage='extract'
                   ORDER BY id"""
            )
        ]
        assert codes == ["fit_crc_invalid", "fit_crc_invalid"]
        assert conn.execute(
            "SELECT count(*) FROM source_revisions WHERE resource_kind='activity_fit'"
        ).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("case", "payload_factory", "error_code"),
    [
        ("all_crc_invalid", lambda running, bouldering: bytes(bytearray(running[:-1]) + bytes([running[-1] ^ 1])), "fit_crc_invalid"),
        ("no_session", lambda running, bouldering: _minimal_fit_without_session(), "fit_no_session"),
        ("identity_mismatch", lambda running, bouldering: bouldering, "fit_identity_mismatch"),
        ("no_fit", lambda running, bouldering: _zip_payload([("readme.txt", b"none")]), "fit_missing"),
        ("bad_zip", lambda running, bouldering: b"PK\x03\x04broken", "fit_zip_invalid"),
    ],
)
def test_candidate_failure_matrix_records_expected_gap_without_canonical(
    tmp_path: Path, case: str, payload_factory, error_code: str,
) -> None:
    root = Path(__file__).resolve().parents[1] / "test_data" / "new"
    running = (root / "Running.fit").read_bytes()
    bouldering = (root / "Bouldering.fit").read_bytes()
    tool, _transport, foundation = _activity_pipeline(
        tmp_path, payload_factory(running, bouldering),
    )
    receipt = _full(tool, f"failure-{case}")
    assert receipt.status == "partial"
    with sqlite3.connect(foundation.database_path) as conn:
        assert conn.execute(
            "SELECT reason_code FROM garmin_sync_gaps WHERE resource_kind='activity_fit'"
        ).fetchone()[0] == error_code
        assert conn.execute(
            "SELECT count(*) FROM activity_source_revisions WHERE source_role='activity_fit'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM activity_samples"
        ).fetchone()[0] == 0


def test_different_valid_candidates_are_quarantined_repeatably_then_unique_fit_resolves_issue_and_gap(
    tmp_path: Path,
) -> None:
    fit = (Path(__file__).resolve().parents[1] / "test_data" / "new" / "Running.fit").read_bytes()
    variant = _valid_fit_variant(fit)
    invalid = bytearray(fit)
    invalid[1000] ^= 1
    invalid = bytes(invalid)
    hashes = sorted((hashlib.sha256(fit).hexdigest(), hashlib.sha256(variant).hexdigest()))
    invalid_hash = hashlib.sha256(invalid).hexdigest()
    all_hashes = sorted([*hashes, invalid_hash])
    payload = _zip_payload([
        ("original.fit", fit), ("invalid.fit", invalid), ("variant.fit", variant),
    ])
    tool, transport, foundation = _activity_pipeline(tmp_path, payload)

    ambiguous = _full(tool, "ambiguous-first")
    assert ambiguous.status == "partial"
    receipt_json = ambiguous.json()
    assert all(candidate_hash not in receipt_json for candidate_hash in all_hashes)
    with sqlite3.connect(foundation.database_path) as conn:
        candidate_rows = conn.execute(
            """SELECT raw_objects.sha256,raw_objects.relative_path,raw_objects.media_type,
                      raw_objects.resource_kind,source_revisions.provider_object_id
               FROM raw_objects JOIN source_revisions
                 ON source_revisions.raw_object_id=raw_objects.id
               WHERE raw_objects.resource_kind='activity_fit_candidate'
               ORDER BY raw_objects.sha256"""
        ).fetchall()
        assert len(candidate_rows) == 2
        assert all(row[1].endswith(".fit") for row in candidate_rows)
        assert all(row[2] == "application/octet-stream" for row in candidate_rows)
        assert all(row[3] == "activity_fit_candidate" for row in candidate_rows)
        assert all(len(row[4]) == 64 and row[4] not in {"1", row[0]} for row in candidate_rows)
        assert {row[4] for row in candidate_rows} == {
            tool._identity_hmac(f"fit-candidate:1:{candidate_hash}")
            for candidate_hash in hashes
        }
        assert len({row[4] for row in candidate_rows}) == 2
        details = json.loads(conn.execute(
            "SELECT details_json FROM data_quality_issues WHERE issue_code='ambiguous_activity_fit'"
        ).fetchone()[0])
        assert details["candidate_count"] == 3
        assert details["valid_candidate_count"] == 2
        assert [entry["hash"] for entry in details["candidates"]] == all_hashes
        errors = {entry["hash"]: entry["error_code"] for entry in details["candidates"]}
        assert errors == {hashes[0]: None, hashes[1]: None, invalid_hash: "fit_crc_invalid"}
        assert set(details) == {"candidate_count", "valid_candidate_count", "candidates"}
        assert conn.execute(
            "SELECT count(*) FROM activity_source_revisions WHERE source_role='activity_fit' AND is_active=1"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT status FROM garmin_sync_gaps WHERE resource_kind='activity_fit'"
        ).fetchone()[0] == "open"

    transport.payload = _zip_payload([
        ("variant.fit", variant), ("invalid.fit", invalid), ("original.fit", fit),
    ])
    repeated = _full(tool, "ambiguous-repeat")
    assert repeated.status == "partial"
    with sqlite3.connect(foundation.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM raw_objects WHERE resource_kind='activity_fit_candidate'"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT count(*) FROM source_revisions WHERE resource_kind='activity_fit_candidate'"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT count(*) FROM data_quality_issues WHERE issue_code='ambiguous_activity_fit'"
        ).fetchone()[0] == 1

    transport.payload = fit
    resolved = _full(tool, "ambiguous-resolved")
    assert resolved.status == "succeeded"
    with sqlite3.connect(foundation.database_path) as conn:
        assert conn.execute(
            "SELECT status FROM data_quality_issues WHERE issue_code='ambiguous_activity_fit'"
        ).fetchone()[0] == "resolved"
        assert conn.execute(
            "SELECT status FROM garmin_sync_gaps WHERE resource_kind='activity_fit'"
        ).fetchone()[0] == "resolved"
        assert conn.execute(
            "SELECT count(*) FROM raw_objects WHERE resource_kind='activity_fit_candidate'"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT count(*) FROM activity_source_revisions WHERE source_role='activity_fit' AND is_active=1"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM source_revisions WHERE resource_kind='activity_fit' AND is_current=1"
        ).fetchone()[0] == 1
    assert not list((tmp_path / "data").glob(".fit-download-*"))
    assert not list((tmp_path / "data").rglob("original.zip"))


def test_activity_fit_gap_resolution_is_scoped_to_one_activity_key_and_day(
    tmp_path: Path,
) -> None:
    fit = (Path(__file__).resolve().parents[1] / "test_data" / "new" / "Running.fit").read_bytes()
    variant = _valid_fit_variant(fit)
    corrupt = bytearray(variant)
    corrupt[1000] ^= 1
    start, _sport = _session(
        Path(__file__).resolve().parents[1] / "test_data" / "new" / "Running.fit"
    )
    day = "2026-07-19"
    key_a, key_b = "garmin:activity:101", "garmin:activity:202"

    class TwoActivityTransport:
        payloads = {"101": fit, "202": bytes(corrupt)}

        def login(self): pass
        def identity(self): return "l2-11-gap-isolation"
        def fetch_health(self, *_args): return []
        def fetch_range(self, *_args): return []
        def fetch_account(self, *_args): return []
        def list_activities(self, *_args):
            return [
                {"activityId": 101, "startTimeGMT": start},
                {"activityId": 202, "startTimeGMT": start},
            ]
        def activity_summary(self, activity_id):
            return {
                "activityId": int(activity_id),
                "activityName": f"fixture-{activity_id}",
                "activityType": {"typeKey": "running"},
                "startTimeGMT": start,
                "duration": 1,
            }
        def activity_original(self, activity_id): return self.payloads[str(activity_id)]

    root = tmp_path / "data"
    foundation = FoundationConfig(
        root, root / "data.db", root / "raw", root / "state",
        root / "state/ready", root / "state/locks/f.lock",
    )
    assert FoundationTool(foundation).execute(
        FoundationRequest("init", "l2-11", "2026-01-01T00:00:00Z")
    ).status == "initialized"
    transport = TwoActivityTransport()
    tool = GarminCollectionTool(
        GarminConfig(
            foundation.database_path, foundation.raw_root,
            foundation.state_root, "2026-01-01", request_min_interval_ms=0,
        ),
        transport,
        sleep=lambda _: None,
        clock=lambda: datetime(2026, 7, 20),
    )
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    def fit_full(invocation: str):
        return tool.execute(SyncRequest(
            "full",
            through_local_date=day,
            resource_kinds=("activity_fit",),
            invocation_id=invocation,
        ))

    with tool.repo.connect() as conn:
        subject = tool.repo.subject(conn)
        tool.repo.gap(conn, subject, "activity_fit", key_a, day, "extract", "fit_missing")
        tool.repo.gap(
            conn, subject, "activity_fit", key_a, day, "parse",
            "fit_parse_failed", deferred=True,
        )
        tool.repo.gap(
            conn, subject, "activity_fit", key_b, day, "extract",
            "fit_crc_invalid", deferred=True,
        )
        # Same logical key but a different resource/date must never be swept
        # up by activity A's successful FIT.
        tool.repo.gap(
            conn, subject, "activity_summary", key_a, day, "extract",
            "provider_error",
        )
        tool.repo.gap(
            conn, subject, "activity_fit", key_a, "2026-07-18", "extract",
            "fit_missing",
        )

    first = fit_full("gap-isolation-a")
    assert first.status == "partial"
    with sqlite3.connect(foundation.database_path) as conn:
        assert first.open_gap_count == conn.execute(
            "SELECT count(*) FROM garmin_sync_gaps WHERE status IN ('open','deferred')"
        ).fetchone()[0]
        assert first.open_gap_count >= 3
        statuses = {
            (row[0], row[1], row[2], row[3]): row[4]
            for row in conn.execute(
                """SELECT resource_kind,logical_object_key,
                          window_start_local_date,stage,status
                   FROM garmin_sync_gaps"""
            )
        }
        assert statuses[("activity_fit", key_a, day, "extract")] == "resolved"
        assert statuses[("activity_fit", key_a, day, "parse")] == "resolved"
        assert statuses[("activity_fit", key_b, day, "extract")] == "open"
        assert statuses[("activity_summary", key_a, day, "extract")] == "open"
        assert statuses[("activity_fit", key_a, "2026-07-18", "extract")] == "open"
        run_id = conn.execute(
            "SELECT id FROM garmin_sync_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    with tool.repo.connect() as conn:
        tool.repo.coverage(conn, subject, "activity_fit", day, "fetched", None, 1)
        tool.repo.advance_cursor(conn, subject, "activity_fit", day, run_id)
        assert conn.execute(
            "SELECT 1 FROM garmin_sync_cursors WHERE subject_id=? AND resource_kind='activity_fit'",
            (subject,),
        ).fetchone() is None

    transport.payloads["202"] = variant
    second = fit_full("gap-isolation-b")
    assert second.status == "succeeded"
    assert second.open_gap_count == first.open_gap_count - 1
    with sqlite3.connect(foundation.database_path) as conn:
        assert second.open_gap_count == conn.execute(
            "SELECT count(*) FROM garmin_sync_gaps WHERE status IN ('open','deferred')"
        ).fetchone()[0]
        resolved_rows = conn.execute(
            """SELECT logical_object_key,stage,resolved_at_utc
               FROM garmin_sync_gaps
               WHERE resource_kind='activity_fit'
                 AND window_start_local_date=? AND status='resolved'
               ORDER BY logical_object_key,stage""",
            (day,),
        ).fetchall()
        assert [(row[0], row[1]) for row in resolved_rows] == [
            (key_a, "extract"), (key_a, "parse"), (key_b, "extract"),
        ]
        resolved_timestamps = [row[2] for row in resolved_rows]
        assert conn.execute(
            """SELECT count(*) FROM activity_source_revisions
               WHERE source_role='activity_fit' AND is_active=1"""
        ).fetchone()[0] == 2
        run_id = conn.execute(
            "SELECT id FROM garmin_sync_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    with tool.repo.connect() as conn:
        tool.repo.advance_cursor(conn, subject, "activity_fit", day, run_id)
        assert conn.execute(
            """SELECT complete_through_local_date FROM garmin_sync_cursors
               WHERE subject_id=? AND resource_kind='activity_fit'""",
            (subject,),
        ).fetchone()[0] == day

    third = fit_full("gap-isolation-repeat")
    assert third.status == "succeeded"
    assert third.open_gap_count == second.open_gap_count
    with sqlite3.connect(foundation.database_path) as conn:
        assert [
            row[0] for row in conn.execute(
                """SELECT resolved_at_utc FROM garmin_sync_gaps
                   WHERE resource_kind='activity_fit'
                     AND window_start_local_date=? AND status='resolved'
                   ORDER BY logical_object_key,stage""",
                (day,),
            )
        ] == resolved_timestamps
        assert conn.execute(
            "SELECT status FROM garmin_sync_gaps WHERE resource_kind='activity_summary'"
        ).fetchone()[0] == "open"
        assert conn.execute(
            """SELECT status FROM garmin_sync_gaps
               WHERE resource_kind='activity_fit' AND window_start_local_date='2026-07-18'"""
        ).fetchone()[0] == "open"


def test_ambiguous_candidate_archive_or_issue_failure_never_switches_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fit = (Path(__file__).resolve().parents[1] / "test_data" / "new" / "Running.fit").read_bytes()
    variant = _valid_fit_variant(fit)
    tool, transport, foundation = _activity_pipeline(tmp_path, fit)
    assert _full(tool, "canonical-first").status == "succeeded"
    with sqlite3.connect(foundation.database_path) as conn:
        canonical = conn.execute(
            "SELECT source_revision_id FROM activity_source_revisions WHERE source_role='activity_fit' AND is_active=1"
        ).fetchone()[0]

    transport.payload = _zip_payload([("one.fit", fit), ("two.fit", variant)])
    original_archive = tool.repo.archive

    def fail_candidate_archive(conn, resource, *args, **kwargs):
        if resource == "activity_fit_candidate":
            raise RuntimeError("candidate archive failed")
        return original_archive(conn, resource, *args, **kwargs)

    monkeypatch.setattr(tool.repo, "archive", fail_candidate_archive)
    assert _full(tool, "candidate-archive-failure").status == "partial"
    with sqlite3.connect(foundation.database_path) as conn:
        assert conn.execute(
            "SELECT source_revision_id FROM activity_source_revisions WHERE source_role='activity_fit' AND is_active=1"
        ).fetchone()[0] == canonical

    monkeypatch.setattr(tool.repo, "archive", original_archive)
    with sqlite3.connect(foundation.database_path) as conn:
        conn.execute(
            """CREATE TRIGGER fail_ambiguous_quality
               BEFORE INSERT ON data_quality_issues
               WHEN NEW.issue_code='ambiguous_activity_fit'
               BEGIN SELECT RAISE(ABORT,'quality insert failed'); END"""
        )
    assert _full(tool, "candidate-issue-failure").status == "partial"
    with sqlite3.connect(foundation.database_path) as conn:
        assert conn.execute(
            "SELECT source_revision_id FROM activity_source_revisions WHERE source_role='activity_fit' AND is_active=1"
        ).fetchone()[0] == canonical
        assert conn.execute(
            "SELECT count(*) FROM data_quality_issues WHERE issue_code='ambiguous_activity_fit'"
        ).fetchone()[0] == 0

@pytest.mark.parametrize("filename,expected", [
    ("Running.fit", "running"), ("Bouldering.fit", "bouldering"),
    ("Indoor Climbing.fit", "indoor_climbing"), ("力量训练.fit", "strength"),
    ("骑行.fit", "cycling"), ("hiking.fit", "hiking"),
])
def test_default_pipeline_archives_and_projects_representative_fit_then_replays_noop(tmp_path: Path, filename: str, expected: str) -> None:
    sample = Path(__file__).resolve().parents[1] / "test_data" / "new" / filename
    start, sport = _session(sample)
    class Transport:
        def login(self): pass
        def identity(self): return "l2-11-end-to-end"
        def fetch_health(self, *_args): return []
        def fetch_range(self, *_args): return []
        def fetch_account(self, *_args): return []
        def list_activities(self, *_args): return [{"activityId": 1, "startTimeGMT": start}]
        def activity_summary(self, _id):
            type_key = {"training": "strength_training", "rock_climbing": expected}.get(sport, sport)
            return {"activityId": 1, "activityName": "fixture", "activityType": {"typeKey": type_key}, "startTimeGMT": start, "duration": 1}
        def activity_original(self, _id):
            # ORIGINAL is a ZIP in production.  Exercise that transient path
            # for both climbing samples while keeping all six fixtures covered.
            fit = sample.read_bytes()
            return _original_zip(fit) if expected in {"bouldering", "indoor_climbing"} else fit
    root = tmp_path / "data"
    foundation = FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state/ready", root / "state/locks/f.lock")
    assert FoundationTool(foundation).execute(FoundationRequest("init", "l2-11", "2026-01-01T00:00:00Z")).status == "initialized"
    tool = GarminCollectionTool(GarminConfig(foundation.database_path, foundation.raw_root, foundation.state_root, "2026-01-01", request_min_interval_ms=0), Transport(), sleep=lambda _: None, clock=lambda: datetime(2026, 7, 20))
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    first = tool.execute(SyncRequest("full", through_local_date="2026-07-19", invocation_id="fit-first"))
    assert first.status == "succeeded"
    import sqlite3
    metric_source_count: int | None = None
    with sqlite3.connect(foundation.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM raw_objects WHERE resource_kind='activity_fit'").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM activity_samples").fetchone()[0] > 0
        if expected == "running":
            assert conn.execute("SELECT count(*) FROM fit_metric_definitions").fetchone()[0] == 24
            developer = conn.execute("""
                SELECT json_extract(extras_json, '$.dr_gct.value'),
                       json_extract(extras_json, '$.dr_gct.unit'),
                       json_extract(extras_json, '$.dr_gct.field_definition_number'),
                       json_extract(extras_json, '$.dr_gct.developer_data_index'),
                       json_extract(extras_json, '$.dr_gct.is_developer')
                FROM activity_samples
                WHERE json_extract(extras_json, '$.dr_gct.value') IS NOT NULL LIMIT 1
            """).fetchone()
            assert developer == (1417, "ms", 4, 0, 1)
            heart_metadata = conn.execute("""
                SELECT json_extract(extras_json, '$._field_metadata.heart_rate.value'),
                       json_extract(extras_json, '$._field_metadata.heart_rate.unit'),
                       json_extract(extras_json, '$._field_metadata.heart_rate.field_definition_number'),
                       json_extract(extras_json, '$._field_metadata.heart_rate.developer_data_index'),
                       json_extract(extras_json, '$._field_metadata.heart_rate.is_developer')
                FROM activity_samples ORDER BY sample_index LIMIT 1
            """).fetchone()
            assert heart_metadata == (111, "bpm", 3, None, 0)
            assert conn.execute("""
                SELECT source_kind,device_id,developer_data_index,attribution_method,confidence
                FROM activity_metric_sources WHERE metric_key='dr_gct'
            """).fetchone() == ("developer_fit", None, 0, "explicit_developer", 1.0)
            assert conn.execute("""
                SELECT source_kind,device_id,developer_data_index,attribution_method
                FROM activity_metric_sources WHERE metric_key='heart_rate'
            """).fetchone() == ("standard_fit", None, None, "unknown")
            assert conn.execute("SELECT count(*) FROM activity_devices WHERE device_role='developer_app'").fetchone()[0] == 1
            metric_source_count = conn.execute("SELECT count(*) FROM activity_metric_sources").fetchone()[0]
            sample_row = conn.execute("SELECT speed_mps,extras_json FROM activity_samples ORDER BY sample_index LIMIT 1").fetchone()
            assert sample_row[0] == 0.0
            assert "position_lat_semicircles" not in json.loads(sample_row[1])
            session = conn.execute("SELECT start_time_utc,end_time_utc,extras_json,source_map_json FROM activities").fetchone()
            session_extras = json.loads(session[2])
            assert session_extras["fit_session"]["source_revision_id"]
            assert session_extras["fit_session"]["fields"]["timestamp"]["field_definition_number"] == 253
            assert json.loads(session[3])["fit_session"]["source_kind"] == "fit_session"
            assert session[1] != session_extras["fit_session"]["fields"]["timestamp"]["value"]
        else:
            assert conn.execute("SELECT count(*) FROM activity_metric_sources WHERE source_kind='developer_fit'").fetchone()[0] == 0
        if expected == "hiking":
            assert conn.execute("SELECT count(*) FROM course_points").fetchone()[0] == 34
            low_lat, high_lat, low_lon, high_lon = conn.execute("SELECT min(latitude),max(latitude),min(longitude),max(longitude) FROM course_points").fetchone()
            assert 32 < low_lat <= high_lat < 34
            assert 103 < low_lon <= high_lon < 105
            assert conn.execute("SELECT count(*) FROM activity_aux_messages WHERE message_name='course_point_evidence'").fetchone()[0] == 34
            aux = json.loads(conn.execute("SELECT payload_json FROM activity_aux_messages WHERE message_name='timestamp_correlation' LIMIT 1").fetchone()[0])
            assert aux["system_timestamp"]["field_definition_number"] == 1
            unknown = conn.execute("SELECT field_signature_json,first_timestamp_utc,last_timestamp_utc FROM fit_unknown_message_catalog WHERE global_message_number=534").fetchone()
            signature = json.loads(unknown[0])
            assert {"name", "field_definition_number", "unit", "developer_data_index", "is_developer"} <= set(signature[0])
            assert unknown[1] is not None and unknown[2] is not None and unknown[1] <= unknown[2]
        assert conn.execute("SELECT count(*) FROM activity_source_revisions WHERE source_role='activity_fit' AND is_active=1").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM activity_segments").fetchone()[0] > 0
        assert conn.execute("SELECT count(*) FROM devices").fetchone()[0] > 0
        assert conn.execute("SELECT count(*) FROM fit_unknown_message_catalog").fetchone()[0] > 0
        if expected == "bouldering":
            routes = conn.execute("""
                SELECT segment_type,grade_raw,grade_system,grade_display,completed,falls,ascent_meters
                FROM climbing_routes JOIN activity_segments ON activity_segments.id=climbing_routes.segment_id
                ORDER BY activity_segments.segment_index
            """).fetchall()
            assert len(routes) == 17
            assert tuple(routes[0]) == ("climb_active", "0", "font", "1", 1, None, None)
            assert tuple(routes[-1]) == ("climb_active", "4", "font", "4+", 0, None, None)
            outcomes = conn.execute("""
                SELECT json_extract(activity_segments.extras_json, '$.unknown_71')
                FROM climbing_routes JOIN activity_segments ON activity_segments.id=climbing_routes.segment_id
                ORDER BY activity_segments.segment_index
            """).fetchall()
            assert [row[0] for row in (outcomes[0], outcomes[-1])] == [3, 2]
        if expected == "indoor_climbing":
            routes = conn.execute("""
                SELECT segment_type,grade_raw,grade_system,grade_display,completed,falls,ascent_meters
                FROM climbing_routes JOIN activity_segments ON activity_segments.id=climbing_routes.segment_id
                ORDER BY activity_segments.segment_index
            """).fetchall()
            assert len(routes) == 4
            assert tuple(routes[0]) == ("climb_active", "10", "font", "6a+", 1, 0, 12.0)
            assert tuple(routes[-1]) == ("climb_active", "10", "font", "6a+", 1, 0, 11.0)
            assert conn.execute("SELECT count(*) FROM activity_aux_messages WHERE message_name='split_summary'").fetchone()[0] == 2
        if expected == "strength":
            assert conn.execute("SELECT count(*) FROM activity_segments WHERE segment_type='strength_active'").fetchone()[0] == 30
            assert conn.execute("SELECT count(*) FROM activity_segments WHERE segment_type='strength_rest'").fetchone()[0] == 28
            assert conn.execute("SELECT count(*) FROM strength_sets").fetchone()[0] == 30
            sets = conn.execute("""
                SELECT activity_segments.segment_index,
                       json_extract(activity_segments.extras_json, '$.message_index'),
                       strength_sets.workout_step_index,strength_sets.exercise_category,
                       strength_sets.raw_exercise_number,strength_sets.exercise_name,
                       strength_sets.repetitions,strength_sets.weight_kg,strength_sets.duration_seconds
                FROM strength_sets JOIN activity_segments ON activity_segments.id=strength_sets.segment_id
                ORDER BY activity_segments.segment_index
            """).fetchall()
            assert [tuple(row) for row in sets[:3]] == [
                (0, 0, 0, "warmup", None, "猫牛式、胸椎旋转、肩绕环、弹力带拉伸", None, None, 372.252),
                (1, 1, 1, "pull_up", 38, "辅助引体", 6, 33.0, 35.333),
                (2, 3, 1, "pull_up", 38, "辅助引体", 6, 29.0, 28.97),
            ]
            assert [tuple(row) for row in sets[-2:]] == [
                (28, 55, 28, "deadlift", 23, "罗马尼亚硬拉", 0, 0.0, 1.502),
                (29, 57, 31, "cooldown", None, "有氧运动", None, None, 152.494),
            ]
            zero = sets[-2]
            assert zero[6:8] == (0, 0.0)
            assert conn.execute("SELECT count(*) FROM activity_segments WHERE segment_type='workout_step'").fetchone()[0] == 32
            assert conn.execute("SELECT count(*) FROM activity_aux_messages WHERE message_name='exercise_title'").fetchone()[0] == 10
            assert conn.execute("""
                SELECT json_extract(extras_json, '$.category'),json_extract(extras_json, '$.category_subtype')
                FROM activity_segments WHERE segment_type='strength_active' ORDER BY segment_index LIMIT 1
            """).fetchone() == ('[2,2,2]', '[null,null,null]')
        if expected == "hiking":
            assert conn.execute("SELECT count(*) FROM course_points").fetchone()[0] > 0
    second = tool.execute(SyncRequest("full", through_local_date="2026-07-19", invocation_id="fit-second"))
    assert second.status == "succeeded" and second.counts["unchanged"] > 0
    if expected == "running":
        with sqlite3.connect(foundation.database_path) as conn:
            assert conn.execute("SELECT count(*) FROM activity_metric_sources").fetchone()[0] == metric_source_count
    assert not list(root.glob(".fit-download-*"))


def test_changed_fit_keeps_revision_bound_history_and_switches_only_active_canonical(
    tmp_path: Path,
) -> None:
    fit = (Path(__file__).resolve().parents[1] / "test_data" / "new" / "Running.fit").read_bytes()
    variant = _valid_fit_variant(fit)
    tool, transport, foundation = _activity_pipeline(tmp_path, fit)
    assert _full(tool, "revision-original").status == "succeeded"
    with sqlite3.connect(foundation.database_path) as conn:
        old_revision = conn.execute(
            "SELECT source_revision_id FROM activity_source_revisions WHERE source_role='activity_fit' AND is_active=1"
        ).fetchone()[0]
        old_metric_count = conn.execute(
            "SELECT count(*) FROM activity_metric_sources"
        ).fetchone()[0]

    transport.payload = variant
    assert _full(tool, "revision-changed").status == "succeeded"
    with sqlite3.connect(foundation.database_path) as conn:
        active = conn.execute(
            "SELECT source_revision_id FROM activity_source_revisions WHERE source_role='activity_fit' AND is_active=1"
        ).fetchone()[0]
        assert active != old_revision
        assert conn.execute(
            "SELECT is_active FROM activity_source_revisions WHERE source_revision_id=? AND source_role='activity_fit'",
            (old_revision,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT is_current FROM source_revisions WHERE id=?", (old_revision,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT is_current FROM source_revisions WHERE id=?", (active,)
        ).fetchone()[0] == 1
        for table in (
            "activity_samples", "activity_segments", "activity_aux_messages",
            "activity_devices", "fit_metric_definitions",
            "fit_unknown_message_catalog",
        ):
            assert conn.execute(
                f"SELECT count(*) FROM {table} WHERE source_revision_id=?",
                (old_revision,),
            ).fetchone()[0] > 0
            assert conn.execute(
                f"SELECT count(*) FROM {table} WHERE source_revision_id=?",
                (active,),
            ).fetchone()[0] > 0
        assert conn.execute(
            "SELECT count(*) FROM activity_metric_sources"
        ).fetchone()[0] == old_metric_count
        extras, source_map = conn.execute(
            "SELECT extras_json,source_map_json FROM activities"
        ).fetchone()
        extras, source_map = json.loads(extras), json.loads(source_map)
        assert {entry["source_revision_id"] for entry in extras["fit_sessions"]} == {active}
        assert source_map["fit_sessions"]["source_revision_id"] == active
        assert conn.execute(
            "SELECT count(*) FROM raw_objects WHERE resource_kind='activity_fit'"
        ).fetchone()[0] == 2


def test_fit_identity_hmacs_are_stable_canonical_and_absent_in_operational_text(
    tmp_path: Path,
) -> None:
    fit = (Path(__file__).resolve().parents[1] / "test_data" / "new" / "Running.fit").read_bytes()
    tool, _transport, foundation = _activity_pipeline(tmp_path, fit)
    receipt = _full(tool, "hmac-fit-identities")
    assert receipt.status == "succeeded"
    application_tuple = (91, 169, 170, 153, 29, 110, 65, 77, 153, 175, 126, 10, 142, 225, 32, 178)
    application_list = list(application_tuple)
    serial_a, serial_b = "3610771675", "33554456"
    serial_a_hmac = tool._identity_hmac(f"garmin:{serial_a}")
    serial_b_hmac = tool._identity_hmac(f"garmin:{serial_b}")
    tuple_hmac = tool._identity_hmac(
        f"garmin-developer:0:{tool._fit_json_value(application_tuple)}"
    )
    list_hmac = tool._identity_hmac(
        f"garmin-developer:0:{tool._fit_json_value(application_list)}"
    )
    assert serial_a_hmac == tool._identity_hmac(f"garmin:{serial_a}")
    assert serial_a_hmac != serial_b_hmac
    assert tuple_hmac == list_hmac
    assert tuple_hmac != tool._identity_hmac(
        f"garmin-developer:0:{tool._fit_json_value(application_list[:-1] + [179])}"
    )
    assert all(raw not in {serial_a_hmac, serial_b_hmac, tuple_hmac} for raw in (serial_a, serial_b))
    assert (foundation.state_root / "secrets" / "garmin-identity.key").stat().st_mode & 0o777 == 0o600

    with sqlite3.connect(foundation.database_path) as conn:
        device_hashes = {row[0] for row in conn.execute("SELECT device_uid_hash FROM devices")}
        assert {serial_a_hmac, serial_b_hmac, tuple_hmac} <= device_hashes
        operational = "\n".join(conn.iterdump())
        assert serial_a not in operational
        # The application sequence must not be persisted as tuple/list text.
        assert str(application_tuple) not in operational
        assert str(application_list) not in operational
        for table in ("garmin_sync_items", "garmin_sync_gaps", "data_quality_issues"):
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            assert serial_a not in repr(rows)
            assert str(application_list) not in repr(rows)
    assert serial_a not in receipt.json()
    assert str(application_list) not in receipt.json()
    for log_path in foundation.data_root.rglob("*.log"):
        log_text = log_path.read_text(errors="replace")
        assert serial_a not in log_text
        assert str(application_list) not in log_text


def test_fit_projection_failure_keeps_existing_current_revision_and_cleans_temp_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bouldering = Path(__file__).resolve().parents[1] / "test_data" / "new" / "Bouldering.fit"
    start, sport = _session(bouldering)

    class Transport:
        payload = _original_zip(bouldering.read_bytes())

        def login(self): pass
        def identity(self): return "l2-11-project-failure"
        def fetch_health(self, *_args): return []
        def fetch_range(self, *_args): return []
        def fetch_account(self, *_args): return []
        def list_activities(self, *_args): return [{"activityId": 1, "startTimeGMT": start}]
        def activity_summary(self, _id):
            return {"activityId": 1, "activityName": "fixture", "activityType": {"typeKey": "bouldering"}, "startTimeGMT": start, "duration": 1}
        def activity_original(self, _id): return self.payload

    root = tmp_path / "data"
    foundation = FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state/ready", root / "state/locks/f.lock")
    assert FoundationTool(foundation).execute(FoundationRequest("init", "l2-11", "2026-01-01T00:00:00Z")).status == "initialized"
    transport = Transport()
    tool = GarminCollectionTool(GarminConfig(foundation.database_path, foundation.raw_root, foundation.state_root, "2026-01-01", request_min_interval_ms=0), transport, sleep=lambda _: None, clock=lambda: datetime(2026, 7, 20))
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    assert tool.execute(SyncRequest("full", through_local_date="2026-07-19", invocation_id="fit-good")).status == "succeeded"

    import sqlite3
    with sqlite3.connect(foundation.database_path) as conn:
        old_revision = conn.execute("SELECT id FROM source_revisions WHERE resource_kind='activity_fit' AND is_current=1").fetchone()[0]
        old_active = conn.execute("SELECT source_revision_id FROM activity_source_revisions WHERE source_role='activity_fit' AND is_active=1").fetchone()[0]
        before_counts = {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "activity_samples", "activity_segments", "climbing_routes",
                "activity_aux_messages", "activity_devices",
                "fit_unknown_message_catalog", "activity_metric_sources",
                "course_points",
            )
        }
        before_activity = conn.execute(
            "SELECT extras_json,source_map_json FROM activities"
        ).fetchone()

    transport.payload = _original_zip(_valid_fit_variant(bouldering.read_bytes()))
    monkeypatch.setattr(tool, "_project_fit", lambda *_args: (_ for _ in ()).throw(RuntimeError("projection failed")))
    receipt = tool.execute(SyncRequest("full", through_local_date="2026-07-19", invocation_id="fit-project-failure"))
    assert receipt.status == "partial"
    with sqlite3.connect(foundation.database_path) as conn:
        revisions = conn.execute("SELECT id,is_current,parsed_at_utc FROM source_revisions WHERE resource_kind='activity_fit' ORDER BY revision_no").fetchall()
        assert revisions[0] == (old_revision, 1, revisions[0][2])
        assert revisions[1][1:] == (0, None)
        assert conn.execute("SELECT source_revision_id FROM activity_source_revisions WHERE source_role='activity_fit' AND is_active=1").fetchone()[0] == old_active
        assert conn.execute("SELECT count(*) FROM raw_objects WHERE resource_kind='activity_fit'").fetchone()[0] == 2
        assert {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in before_counts
        } == before_counts
        assert conn.execute(
            "SELECT extras_json,source_map_json FROM activities"
        ).fetchone() == before_activity
    assert not list(root.glob(".fit-download-*"))
    assert not list(root.rglob("original.zip"))
