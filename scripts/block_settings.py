"""Validated development-block policy loaded from the user profile."""

from activity_settings import load_config


LEGACY_STRATEGY = "legacy_workday_windows"
CLUSTER_STRATEGY = "activity_clusters"
DEFAULT_CLUSTER_POLICY = {
    "strategy": CLUSTER_STRATEGY,
    "inactivity_gap_minutes": 45,
    "minimum_block_minutes": 30,
    "maximum_block_minutes": 90,
}


def _validate_policy(value, namespace="block_policy"):
    if not isinstance(value, dict):
        raise ValueError(f"{namespace} must be an object")
    unknown = set(value) - set(DEFAULT_CLUSTER_POLICY)
    if unknown:
        raise ValueError(f"Unsupported {namespace} fields: {', '.join(sorted(unknown))}")
    policy = {**DEFAULT_CLUSTER_POLICY, **value}
    if policy["strategy"] not in (LEGACY_STRATEGY, CLUSTER_STRATEGY):
        raise ValueError(f"{namespace}.strategy must be activity_clusters or legacy_workday_windows")
    for key in ("inactivity_gap_minutes", "minimum_block_minutes", "maximum_block_minutes"):
        item = policy[key]
        if not isinstance(item, int) or isinstance(item, bool) or item < 1:
            raise ValueError(f"{namespace}.{key} must be a positive integer")
    if policy["minimum_block_minutes"] > policy["maximum_block_minutes"]:
        raise ValueError(f"{namespace}.minimum_block_minutes cannot exceed maximum_block_minutes")
    if policy["inactivity_gap_minutes"] < policy["minimum_block_minutes"]:
        raise ValueError(f"{namespace}.inactivity_gap_minutes cannot be less than minimum_block_minutes")
    return policy


def block_policy_settings(config_path=None):
    """Return an explicit policy, or None so pre-policy snapshots stay reproducible."""
    config = load_config(config_path)
    if "block_policy" not in config:
        return None
    return _validate_policy(config["block_policy"])


def policy_from_model(normalized_data):
    """Validate a snapshot-embedded policy without reading mutable host configuration."""
    value = normalized_data.get("block_policy")
    if value is None:
        return {"strategy": LEGACY_STRATEGY}
    return _validate_policy(value, "normalized block_policy")
