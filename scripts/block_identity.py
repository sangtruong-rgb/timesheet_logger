"""Stable daily block identities shared by AI preparation and entry assembly."""

import datetime
import re


class BlockIdentityError(ValueError):
    """Block identity is invalid or ambiguous; do not write final results."""


def get_block_id(date, start, end):
    """Date and exact clock boundaries identify a block, independent of list order."""
    try:
        if not isinstance(date, str) or datetime.date.fromisoformat(date).isoformat() != date:
            raise ValueError("Invalid date")
    except ValueError as exc:
        raise BlockIdentityError("Block identity requires a canonical YYYY-MM-DD date") from exc
    clock = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
    if (not isinstance(start, str) or not re.fullmatch(clock, start)
            or not isinstance(end, str) or not (re.fullmatch(clock, end) or end == "24:00")):
        raise BlockIdentityError("Block identity requires HH:MM boundaries")
    if end <= start:
        raise BlockIdentityError("Block interval must end after its start")
    return f"{date}_{start}_{end}"


def index_blocks(blocks):
    """Reject ambiguous candidate identities before asking AI or attaching summaries."""
    if not isinstance(blocks, list):
        raise BlockIdentityError("Candidate blocks must be a JSON array")
    indexed = {}
    for block in blocks:
        if not isinstance(block, dict):
            raise BlockIdentityError("Each candidate block must be an object")
        key = get_block_id(block.get("date"), block.get("start_time"), block.get("end_time"))
        for field in ("commits", "prs", "calendar_events", "calendar_titles"):
            values = block.get(field, [])
            if not isinstance(values, list) or any(not isinstance(v, str if field == "calendar_titles" else dict) for v in values):
                raise BlockIdentityError("Candidate source fields must contain correctly typed arrays")
        if "duration_minutes" in block:
            from interval_validation import validate_interval
            validate_interval(block["date"], block["start_time"], block["end_time"], block["duration_minutes"], block.get("interval"))
        if "block_id" in block and block["block_id"] != key:
            raise BlockIdentityError("Candidate block_id conflicts with its date or interval")
        if key in indexed:
            raise BlockIdentityError("Candidate blocks have duplicate identities")
        indexed[key] = block
    return indexed
