"""Explicit media-account preparation, separate from the ordinary account DB."""
from __future__ import annotations

import time


def prepare_media_profile(state, schema, profile, master_dir):
    """Unlock the real catalog in the caller's dedicated media database.

    The runtime chooses ``media-state.db`` before calling this function. No
    ordinary account, official ownership or currency is imported. The gallery
    prepares only its menu-access aggregate, without battle results or rewards.
    Reopening the mode preserves the media account's identity and selections.
    """
    from .gameplay import seed_starter_profile
    from .gameplay import _Catalog
    from .media_profile import prepare_media_inventory, apply_media_inventory
    from .media_scenes import prepare_media_scenes, unlock_media_musics
    from .media_stories import unlock_media_stories
    from .media_access import prepare_media_access, apply_media_access
    from .media_panorama import prepare_media_panorama

    plan = prepare_media_inventory(schema, master_dir)
    access = prepare_media_access(master_dir)
    prepare_media_panorama(master_dir)
    # Validate all scene definitions before creating or changing an account.
    scenes = prepare_media_scenes(master_dir)
    unlock_media_stories(schema.response_type("/api.User/Get")(), master_dir)
    # This opt-in account is for immediate media use. Store the real final
    # checkpoint of each tutorial instead of requiring photo creation, pulls,
    # or battle tutorials before a gallery can be opened.
    tutorial_steps = {}
    for row in _Catalog(master_dir).rows("Tutorial", required=True):
        kind, entries = row.get("type"), row.get("stepInfo")
        if (type(kind) is not int or kind <= 0 or kind in tutorial_steps
                or not isinstance(entries, list) or not entries
                or any(not isinstance(entry, dict) or type(entry.get("step")) is not int
                       or entry["step"] <= 0 for entry in entries)):
            raise ValueError("Media tutorial master is malformed")
        tutorial_steps[kind] = max(entry["step"] for entry in entries)
    if state.snapshot(profile) is None:
        seed_starter_profile(state, schema, profile, master_dir, manager_name="Local Media")
    now = time.time_ns() // 1_000_000

    def unlock(raw):
        snapshot = schema.response_type("/api.User/Get").FromString(raw)
        if not snapshot.HasField("user"):
            raise ValueError("Media profile has no user state")
        apply_media_inventory(snapshot, plan, obtained_time=now)
        apply_media_access(snapshot, access)
        unlock_media_musics(snapshot, master_dir)
        unlock_media_stories(snapshot, master_dir)
        tutorials = {row.tutorialType: row for row in snapshot.tutorials}
        if len(tutorials) != len(snapshot.tutorials):
            raise ValueError("Media tutorial state is malformed")
        for kind, step in tutorial_steps.items():
            tutorial = tutorials.get(kind)
            if tutorial is None:
                tutorial = snapshot.tutorials.add(tutorialType=kind)
            tutorial.step = max(tutorial.step, step)
        if not snapshot.user.tutorialClearedTime:
            snapshot.user.tutorialClearedTime = now
        return snapshot.SerializeToString()

    state.mutate_snapshot(profile, schema.fingerprint, unlock)
    return scenes
