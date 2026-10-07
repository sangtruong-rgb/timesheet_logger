"""Evidence that cannot be assigned by timestamp; never a timed work entry."""

REASONS = {
    "missing_timestamp": "Missing timestamp",
    "invalid_timestamp": "Invalid timestamp",
    "naive_timestamp": "Timestamp has no timezone",
    "outside_target_day": "Timestamp is outside the selected local day",
    "outside_blocks": "Timestamp is outside all proposed intervals",
}


def validate_unassigned_activity(records):
    if not isinstance(records, list):
        raise ValueError("Unassigned activity must be an array")
    for record in records:
        if (not isinstance(record, dict) or record.get("source") not in ("git", "github", "google_calendar")
                or not isinstance(record.get("reason"), str) or record["reason"] not in REASONS
                or not isinstance(record.get("activity"), dict)
                or (record["source"] == "git" and not isinstance(record["activity"].get("hash"), str))
                or (record["source"] == "github" and record["activity"].get("id") is None)):
            raise ValueError("Unassigned activity requires source, reason and original evidence")
        if record["source"] == "google_calendar" and any(not isinstance(record["activity"].get(field), str)
                                                           for field in ("title", "start", "end")):
            raise ValueError("Calendar review evidence requires title, start and end")


def unpack_activity_snapshot(data, field):
    """Accept legacy arrays, or an explicit envelope without losing review evidence."""
    if isinstance(data, list):
        return data, None
    if (not isinstance(data, dict) or not isinstance(data.get(field), list)
            or "unassigned_activity" not in data):
        raise ValueError(f"Activity snapshot requires {field} and unassigned_activity arrays")
    validate_unassigned_activity(data["unassigned_activity"])
    return data[field], data["unassigned_activity"]


def minimal_review(records):
    """Keep unassigned evidence out of block summaries and remove raw metadata."""
    validate_unassigned_activity(records)
    result = []
    for record in records:
        activity = record["activity"]
        result.append({"source": record["source"], "reason": record["reason"],
                       **({"message": activity.get("message", "")} if record["source"] == "git" else
                          {"title": activity.get("title", "")} if record["source"] == "google_calendar" else
                          {"id": activity["id"], "title": activity.get("title", ""),
                           "action": activity.get("status", "")})})
    return result
