"""Joins server_log.txt's (team, slot, account_id) roster with GSI's
(team, slot) -> hero_id draft data, by (team, slot).

The GSI extraction below is a BEST-EFFORT GUESS at the real key names
(team2/team3 for Radiant/Dire, pick<N>_id for team-relative slot N) - this
is NOT confirmed against a real captured payload. If it doesn't match once
real data is available, only `_extract_picks_from_gsi` needs to change;
everything else in this module (the join itself) is independent of that
guess and stays correct regardless.
"""

_TEAM_KEY = {"radiant": "team2", "dire": "team3"}


def _extract_picks_from_gsi(gsi_raw):
    """Returns {(team, team_slot): hero_id}, best-effort. Empty dict if the
    payload doesn't look like what we expect - never raises."""
    picks = {}
    if not gsi_raw:
        return picks

    draft = gsi_raw.get("draft")
    if not isinstance(draft, dict):
        return picks

    for team, team_key in _TEAM_KEY.items():
        team_data = draft.get(team_key)
        if not isinstance(team_data, dict):
            continue
        for slot in range(5):
            hero_id = team_data.get(f"pick{slot}_id")
            if hero_id:
                picks[(team, slot)] = hero_id
    return picks


def match_current_picks(roster, gsi_raw):
    picks_by_slot = _extract_picks_from_gsi(gsi_raw)
    result = {}
    for team, team_slot, account_id in roster:
        result[account_id] = picks_by_slot.get((team, team_slot))
    return result
