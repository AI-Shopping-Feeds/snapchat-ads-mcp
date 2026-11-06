from . import (
    accounts,
    ad_squads,
    ads,
    audiences,
    bulk,
    campaigns,
    catalogs,
    creatives,
    pixels,
    reporting,
    request,
    targeting,
)

__all__ = [
    "accounts",
    "ad_squads",
    "ads",
    "audiences",
    "bulk",
    "campaigns",
    "catalogs",
    "creatives",
    "pixels",
    "reporting",
    "request",
    "targeting",
]

# Tool groups (one per module) in registration order, which is also the order of
# tools/list. SNAPCHAT_ADS_TOOL_GROUPS selects a subset by these names.
TOOL_GROUPS: tuple[str, ...] = (
    "accounts",
    "campaigns",
    "ad_squads",
    "ads",
    "bulk",
    "creatives",
    "audiences",
    "targeting",
    "pixels",
    "catalogs",
    "reporting",
    "request",
)


def resolve_tool_groups(requested: list[str] | tuple[str, ...]) -> list[str]:
    """Validate group names and return them in registration order.

    An empty selection means every group. Raises RuntimeError naming the
    unknown groups and listing the valid ones.
    """
    if not requested:
        return list(TOOL_GROUPS)
    unknown = [g for g in requested if g not in TOOL_GROUPS]
    if unknown:
        raise RuntimeError(
            f"SNAPCHAT_ADS_TOOL_GROUPS has unknown group(s): {', '.join(unknown)}.\n"
            f"Valid groups: {', '.join(sorted(TOOL_GROUPS))}"
        )
    wanted = set(requested)
    return [g for g in TOOL_GROUPS if g in wanted]
