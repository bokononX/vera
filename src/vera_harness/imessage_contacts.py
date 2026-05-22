"""Read-only iMessage contact metadata discovery."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

from .user_memory import (
    CandidateSourceRef,
    IngestPlan,
    MemoryCandidate,
    MemoryState,
    PageType,
    ProposedWikiEdit,
    SourceRecord,
    SourceRetention,
    apply_ingest_plan,
)


class IMessageContactIngestionError(RuntimeError):
    """Raised when iMessage contact metadata cannot be read safely."""


@dataclass(frozen=True)
class IMessageContactCandidate:
    """One metadata-only iMessage contact candidate."""

    normalized_address: str
    handle_ids: Tuple[str, ...]
    handle_rowids: Tuple[int, ...]
    services: Tuple[str, ...]
    display_names: Tuple[str, ...]
    chat_guids: Tuple[str, ...]
    chat_identifiers: Tuple[str, ...]
    chat_display_names: Tuple[str, ...]

    @property
    def title(self) -> str:
        return "iMessage Contact {}".format(self.normalized_address)

    @property
    def display_label(self) -> str:
        if self.display_names:
            return "{} ({})".format(self.display_names[0], self.normalized_address)
        return self.normalized_address

    @property
    def owner_prompt(self) -> str:
        return (
            "I noticed you text with {}. Who is this, and how should I understand "
            "them in your life?"
        ).format(self.display_label)

    @property
    def stable_identity_fields(self) -> Dict[str, object]:
        return {
            "normalized_address": self.normalized_address,
            "handle_ids": self.handle_ids,
            "handle_rowids": self.handle_rowids,
            "services": self.services,
            "display_names": self.display_names,
            "chat_guids": self.chat_guids,
            "chat_identifiers": self.chat_identifiers,
            "chat_display_names": self.chat_display_names,
        }


@dataclass(frozen=True)
class IMessageContactIngestResult:
    """Dry-run or applied result for an iMessage contact ingest."""

    enabled: bool
    chat_db_path: Path
    memory_root: Path
    owner_user: str
    apply: bool = False
    candidates: Tuple[IMessageContactCandidate, ...] = ()
    plan: Optional[IngestPlan] = None

    def format_human_readable(self) -> str:
        if not self.enabled:
            return "\n".join(
                [
                    "iMessage contact ingestion disabled",
                    "enabled: no",
                    "No Messages database was opened.",
                    "Set VERA_IMESSAGE_CONTACT_INGESTION_ENABLED=true only after granting the Vera process Full Disk Access.",
                ]
            )
        mode = "apply" if self.apply else "dry-run"
        lines = [
            "iMessage contact ingest plan ({})".format(mode),
            "enabled: yes",
            "chat_db_path: {}".format(self.chat_db_path),
            "memory_root: {}".format(self.memory_root),
            "owner_user: {}".format(self.owner_user),
            "candidates: {}".format(len(self.candidates)),
            "",
            "Owner clarification prompts:",
        ]
        if not self.candidates:
            lines.append("- none")
        for candidate in self.candidates:
            lines.append("- {}".format(candidate.owner_prompt))
        lines.extend(["", "Proposed memory edits:"])
        if self.plan is None or not self.plan.edits:
            lines.append("- none")
        else:
            for edit in self.plan.edits:
                lines.append("- {} {}".format(edit.action, edit.relative_path))
        if not self.apply:
            lines.extend(["", "Dry-run only: no files were mutated."])
        return "\n".join(lines)


def ingest_imessage_contacts(
    *,
    enabled: bool,
    chat_db_path: Path,
    memory_root: Path,
    owner_user: str,
    apply: bool = False,
    captured_at: Optional[datetime] = None,
) -> IMessageContactIngestResult:
    """Discover iMessage contact metadata and optionally persist user-memory candidates."""

    if not enabled:
        return IMessageContactIngestResult(
            enabled=False,
            chat_db_path=chat_db_path,
            memory_root=memory_root,
            owner_user=owner_user,
            apply=apply,
        )
    candidates = discover_imessage_contacts(chat_db_path)
    plan = plan_imessage_contact_memory_ingest(
        candidates,
        root=memory_root,
        owner_user=owner_user,
        apply=apply,
        captured_at=captured_at,
    )
    if apply:
        plan = apply_ingest_plan(plan)
    return IMessageContactIngestResult(
        enabled=True,
        chat_db_path=chat_db_path,
        memory_root=memory_root,
        owner_user=owner_user,
        apply=apply,
        candidates=candidates,
        plan=plan,
    )


def discover_imessage_contacts(chat_db_path: Path) -> Tuple[IMessageContactCandidate, ...]:
    """Read local Messages metadata in SQLite read-only mode and return handles."""

    path = chat_db_path.expanduser()
    if not path.exists():
        raise IMessageContactIngestionError(
            "iMessage chat.db not found at {}. On macOS the default is ~/Library/Messages/chat.db; "
            "grant the Vera process Full Disk Access before enabling ingestion.".format(path)
        )
    if not path.is_file():
        raise IMessageContactIngestionError("iMessage chat.db path is not a file: {}".format(path))
    try:
        connection = sqlite3.connect(_sqlite_read_only_uri(path), uri=True)
    except sqlite3.Error as exc:
        raise IMessageContactIngestionError(_read_error(path, exc))
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        _validate_messages_metadata_schema(connection, path)
        rows = connection.execute(_CONTACT_METADATA_QUERY).fetchall()
    except sqlite3.Error as exc:
        raise IMessageContactIngestionError(_read_error(path, exc))
    finally:
        connection.close()
    return _candidates_from_rows(rows)


def plan_imessage_contact_memory_ingest(
    candidates: Sequence[IMessageContactCandidate],
    *,
    root: Path,
    owner_user: str,
    apply: bool = False,
    captured_at: Optional[datetime] = None,
) -> IngestPlan:
    """Build a user-memory ingest plan from metadata-only iMessage contacts."""

    captured = captured_at or datetime.now(timezone.utc)
    source_text = _source_text(candidates)
    source_hash = _sha256(source_text)
    source_id = "src-imessage-contact-ingest-{}".format(source_hash[:16])
    source_record = SourceRecord(
        source_id=source_id,
        path="raw/redactions/{}.json".format(source_id),
        source_type="imessage_contact_metadata",
        channel="imessage",
        captured_at=captured,
        source_event_at=None,
        sha256=source_hash,
        sensitivity="private",
        consent_scope="metadata-only",
        retention=SourceRetention.HASH_ONLY,
        redaction_state="redacted",
        message_count=0,
    )
    memory_candidates = tuple(_memory_candidate(item, source_record) for item in candidates)
    edits: List[ProposedWikiEdit] = []
    for candidate in memory_candidates:
        relative_path = candidate.relative_path
        page_path = root / relative_path
        existing = _read_text_if_exists(page_path)
        if existing is None:
            action = "create"
        elif _candidate_source_already_present(existing, candidate):
            action = "unchanged"
        else:
            action = "update"
        edits.append(
            ProposedWikiEdit(
                action=action,
                path=page_path,
                relative_path=relative_path,
                candidate=candidate,
                contradiction=False,
            )
        )
    return IngestPlan(
        root=root,
        owner_user=owner_user,
        source_record=source_record,
        candidates=memory_candidates,
        confirmation_required_candidates=(),
        edits=tuple(edits),
        contradictions=(),
        withheld_secret_count=0,
        source_text=source_text,
        apply=apply,
    )


_CONTACT_METADATA_QUERY = """
SELECT
  h.ROWID AS handle_rowid,
  h.id AS handle_id,
  h.uncanonicalized_id AS uncanonicalized_id,
  h.service AS handle_service,
  c.guid AS chat_guid,
  c.chat_identifier AS chat_identifier,
  c.display_name AS chat_display_name,
  c.service_name AS chat_service_name,
  chat_counts.handle_count AS chat_handle_count
FROM handle h
LEFT JOIN chat_handle_join chj ON chj.handle_id = h.ROWID
LEFT JOIN chat c ON c.ROWID = chj.chat_id
LEFT JOIN (
  SELECT chat_id, COUNT(DISTINCT handle_id) AS handle_count
  FROM chat_handle_join
  GROUP BY chat_id
) chat_counts ON chat_counts.chat_id = c.ROWID
WHERE h.id IS NOT NULL AND TRIM(h.id) != ''
ORDER BY lower(h.id), lower(COALESCE(h.service, c.service_name, '')), c.guid
"""


def _validate_messages_metadata_schema(connection: sqlite3.Connection, path: Path) -> None:
    required_tables = ("handle", "chat", "chat_handle_join")
    present = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ({})".format(
                ",".join("?" for _ in required_tables)
            ),
            required_tables,
        )
    }
    missing = sorted(set(required_tables) - present)
    if missing:
        raise IMessageContactIngestionError(
            "{} does not look like a supported Messages chat.db; missing table(s): {}".format(
                path,
                ", ".join(missing),
            )
        )


def _sqlite_read_only_uri(path: Path) -> str:
    return "file:{}?mode=ro".format(quote(str(path.resolve()), safe="/"))


def _candidates_from_rows(rows: Iterable[sqlite3.Row]) -> Tuple[IMessageContactCandidate, ...]:
    buckets: Dict[str, Dict[str, object]] = {}
    for row in rows:
        raw_handle = _text(row["handle_id"])
        normalized = normalize_imessage_address(raw_handle)
        if not normalized:
            continue
        bucket = buckets.setdefault(
            normalized,
            {
                "handle_ids": [],
                "handle_rowids": [],
                "services": [],
                "display_names": [],
                "chat_guids": [],
                "chat_identifiers": [],
                "chat_display_names": [],
            },
        )
        _append_unique(bucket["handle_ids"], raw_handle)
        if row["uncanonicalized_id"]:
            _append_unique(bucket["handle_ids"], _text(row["uncanonicalized_id"]))
        if row["handle_rowid"] is not None:
            _append_unique(bucket["handle_rowids"], int(row["handle_rowid"]))
        service = _text(row["handle_service"]) or _text(row["chat_service_name"]) or "unknown"
        _append_unique(bucket["services"], service)
        chat_guid = _text(row["chat_guid"])
        if chat_guid:
            _append_unique(bucket["chat_guids"], chat_guid)
        chat_identifier = _text(row["chat_identifier"])
        if chat_identifier:
            _append_unique(bucket["chat_identifiers"], chat_identifier)
        chat_display_name = _text(row["chat_display_name"])
        if chat_display_name:
            _append_unique(bucket["chat_display_names"], chat_display_name)
            if row["chat_handle_count"] == 1:
                _append_unique(bucket["display_names"], chat_display_name)
    candidates = []
    for normalized, bucket in sorted(buckets.items()):
        candidates.append(
            IMessageContactCandidate(
                normalized_address=normalized,
                handle_ids=tuple(str(item) for item in bucket["handle_ids"]),
                handle_rowids=tuple(int(item) for item in bucket["handle_rowids"]),
                services=tuple(str(item) for item in bucket["services"]),
                display_names=tuple(str(item) for item in bucket["display_names"]),
                chat_guids=tuple(str(item) for item in bucket["chat_guids"]),
                chat_identifiers=tuple(str(item) for item in bucket["chat_identifiers"]),
                chat_display_names=tuple(str(item) for item in bucket["chat_display_names"]),
            )
        )
    return tuple(candidates)


def normalize_imessage_address(value: str) -> str:
    """Normalize an iMessage handle address for cross-run dedupe."""

    text = value.strip()
    if not text:
        return ""
    if "@" in text:
        return text.lower()
    digits = re.sub(r"\D+", "", text)
    if len(digits) >= 7:
        if text.lstrip().startswith("+"):
            return "+{}".format(digits)
        return digits
    return text.lower()


def _memory_candidate(
    candidate: IMessageContactCandidate,
    source_record: SourceRecord,
) -> MemoryCandidate:
    metadata_json = json.dumps(candidate.stable_identity_fields, sort_keys=True)
    support = (
        "Messages handle/chat metadata only; SQLite opened read-only; "
        "message table and message body columns were not read"
    )
    return MemoryCandidate(
        page_type=PageType.PERSON,
        title=candidate.title,
        claim=(
            "Needs owner context: {} This contact candidate was discovered from local "
            "iMessage handle metadata only."
        ).format(candidate.owner_prompt),
        memory_state=MemoryState.OPEN_QUESTION,
        confidence_level="low",
        confidence_score=0.20,
        sensitivity="private",
        prompt_visibility="confirm_first",
        review_status="needs_user_review",
        source_refs=(
            CandidateSourceRef(
                source_id=source_record.source_id,
                path=source_record.path,
                locator="imessage-handle:{}".format(candidate.normalized_address),
                claim="iMessage contact candidate discovered from metadata-only handle records.",
                support=support,
                excerpt_hash=_sha256(metadata_json),
            ),
        ),
        tags=("imessage", "contact-candidate", "needs-owner-context"),
    )


def _source_text(candidates: Sequence[IMessageContactCandidate]) -> str:
    return json.dumps(
        [candidate.stable_identity_fields for candidate in candidates],
        indent=2,
        sort_keys=True,
    )


def _read_text_if_exists(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise IMessageContactIngestionError("cannot read existing memory page {}: {}".format(path, exc))


def _candidate_source_already_present(content: str, candidate: MemoryCandidate) -> bool:
    if not candidate.source_refs:
        return False
    ref = candidate.source_refs[0]
    return (
        ref.source_id in content
        and ref.locator in content
        and candidate.claim in content
    )


def _append_unique(values: object, value: object) -> None:
    assert isinstance(values, list)
    if value not in values:
        values.append(value)


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_error(path: Path, exc: sqlite3.Error) -> str:
    return (
        "Unable to read iMessage chat database at {} in read-only mode: {}. "
        "Verify the file exists, the Vera process has macOS Full Disk Access, "
        "and the database is a local Messages chat.db."
    ).format(path, exc)
