"""Explicit local media-mode story access, without official unlock or rewards.

Only instantiate this handler for the separate media profile. Ordinary profiles
continue to use StoryCatalog/StoryReads. Definitions and resource names come
from the pinned 6.1.1 master; this module creates no ADV scripts, voices,
photographs, paid currency, quest clears, or narrative schedules.
"""
from __future__ import annotations

from types import MappingProxyType

from google.protobuf.message import DecodeError

from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure
from .story_read_rules import MASTER_VERSION, SCHEMA_SHA256


_USER = "/api.User/Get"
_READ = "/api.Story/Read"
_EVENT = "/api.Story/ReadEvent"
_EXTRA = "/api.Story/ReadExtra"
_COMPANY = "/api.Story/ReadCharacterCompanyEnjoyStory"
_RELEASE = "/api.Story/ReleaseEpisode"
_LIST_EVENT = "/api.Story/ListEvent"
_LIST_EXTRA = "/api.Story/ListExtra"
_ROUTES = frozenset((_READ, _EVENT, _EXTRA, _COMPANY, _RELEASE, _LIST_EVENT, _LIST_EXTRA))


def _fail(detail, code=RpcCode.FAILED_PRECONDITION):
    raise RpcFailure(code, detail)


def _identity(value):
    return isinstance(value, str) and bool(value) and not any(ord(c) < 32 for c in value)


def _stories(catalog):
    if catalog.version() != MASTER_VERSION:
        _fail("Media stories require the supported master version")
    rows = catalog.ids("Story", required=True)
    for row in rows.values():
        types, assets = row.get("advPlayTypes"), row.get("advAssetIds")
        if (not isinstance(types, list) or not types
                or any(type(kind) is not int or kind not in range(1, 7) for kind in types)
                or not isinstance(assets, list) or any(not _identity(value) for value in assets)):
            _fail("Media story playback definition is malformed")
        if 6 in types:
            choices = row.get("branchChoices")
            if (types != [6] or assets or not isinstance(choices, list) or not choices
                    or any(not isinstance(choice, dict)
                           or type(choice.get("index")) is not int or choice["index"] <= 0
                           or not _identity(choice.get("advAssetId")) for choice in choices)
                    or len({choice["index"] for choice in choices}) != len(choices)):
                _fail("Media story branch definition is malformed")
        elif len(types) != len(assets):
            _fail("Media story playback sequence is malformed")
    return rows


def unlock_media_stories(snapshot, master_dir):
    """Prepare actual Story rows in a caller-owned *media* snapshot.

    The caller persists this snapshot in its existing transaction. Existing
    Read rows, photo flags and unknown fields are preserved. Only supported
    master stories are added/unlocked; other progress is not synthesized.
    Returns the number of added or corrected rows. No State/network access.
    """
    definitions = _stories(_Catalog(master_dir))
    owned = {}
    for row in snapshot.stories:
        if not row.storyId or row.storyId in owned:
            _fail("Media story state has ambiguous identities")
        if row.storyId in definitions and row.statusType not in (0, 1, 2):
            _fail("Media story state has an unsupported status")
        owned[row.storyId] = row
    changed = 0
    for identity in definitions:
        row = owned.get(identity)
        if row is None:
            snapshot.stories.add(storyId=identity, statusType=1)
            changed += 1
        elif row.statusType == 0 or row.isInvalid:
            if row.statusType == 0:
                row.statusType = 1
            row.isInvalid = False
            changed += 1
    return changed


class MediaStories:
    """All pinned master stories for an explicitly selected local media mode."""

    def __init__(self, schema, state, profile, master_dir=None):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)
        self._story_rows = None
        self._extra_catalog = None

    def _definitions(self):
        if self.schema.fingerprint != SCHEMA_SHA256:
            _fail("Media stories require the supported protocol schema")
        if self._story_rows is None:
            self._story_rows = _stories(self.catalog)
        return self._story_rows

    def _episodes(self, row):
        episodes = row.get("episodes")
        if not isinstance(episodes, list):
            _fail("Media story episodes are malformed")
        numbers = set()
        for episode in episodes:
            if (not isinstance(episode, dict) or type(episode.get("episode")) is not int
                    or episode["episode"] <= 0 or episode["episode"] in numbers
                    or not _identity(episode.get("storyId"))
                    or episode["storyId"] not in self._definitions()):
                _fail("Media story episode reference is malformed")
            numbers.add(episode["episode"])
        return episodes

    def _extras(self):
        """Validate the immutable master links once, without creating a DTO.

        _Catalog already keeps its parsed tables for this handler's lifetime.
        A new handler after a master/language restart builds a fresh index.
        Only master IDs and episode references are cached, never profile
        progress or ordinary-account eligibility.
        """
        self._definitions()
        if self._extra_catalog is not None:
            return self._extra_catalog
        extras = self.catalog.ids("ExtraStory", required=True)
        assigned, parts, episodes_by_story = set(), [], {}
        for identity, master in self.catalog.ids("ExtraStoryPart", required=True).items():
            links = master.get("extraStoryIds")
            if (not isinstance(links, list) or any(not _identity(link) for link in links)
                    or len(set(links)) != len(links)):
                _fail("Media extra story parent references are malformed")
            stories = []
            for link in links:
                extra = extras.get(link)
                if extra is None or extra.get("extraStoryPartId") != identity or link in assigned:
                    _fail("Media extra story parent reference is malformed")
                assigned.add(link)
                episodes = tuple((episode["episode"], episode["storyId"])
                                 for episode in self._episodes(extra))
                stories.append((link, episodes))
                episodes_by_story[link] = episodes
            parts.append((identity, tuple(stories)))
        if assigned != set(extras):
            _fail("Media extra story has no linked parent")
        # Publish only after the complete catalog passes all checks. Failed
        # validation cannot leave a partially usable index behind.
        self._extra_catalog = tuple(parts), MappingProxyType(episodes_by_story)
        return self._extra_catalog

    def _lists(self, path):
        self._definitions()
        result = self.schema.response_type(path)()
        if path == _LIST_EVENT:
            for identity, master in self.catalog.ids("EventStory", required=True).items():
                info = result.infos.add(id=identity)
                for episode in self._episodes(master):
                    info.episodes.add(episode=episode["episode"], unlocked=True)
        else:
            for identity, stories in self._extras()[0]:
                part = result.infos.add(id=identity, unlocked=True)
                for link, episodes in stories:
                    info = part.stories.add(id=link, unlocked=True)
                    for number, _ in episodes:
                        info.episodes.add(episode=number, unlocked=True)
        result.commonResponse.SetInParent()
        return result

    def fill_home(self, result):
        """Use exactly the same media DTOs for Home and ListExtra."""
        if "extraStoryPartInfos" in result.DESCRIPTOR.fields_by_name:
            extra = self._lists(_LIST_EXTRA)
            del result.extraStoryPartInfos[:]
            result.extraStoryPartInfos.extend(extra.infos)

    def _resolve(self, path, request):
        stories = self._definitions()
        if path == _COMPANY:
            character = self.catalog.ids("Character", required=True).get(request.characterId)
            if character is None or request.number <= 0:
                _fail("Unknown media company story", RpcCode.INVALID_ARGUMENT)
            entries = character.get("companyEnjoyStories", [])
            if (not isinstance(entries, list)
                    or any(not isinstance(row, dict) or type(row.get("number")) is not int
                           or row["number"] <= 0 or not _identity(row.get("storyId"))
                           or row["storyId"] not in stories for row in entries)
                    or len({row["number"] for row in entries}) != len(entries)):
                _fail("Media company story references are malformed")
            selected = [row for row in entries if row["number"] == request.number]
            if len(selected) != 1:
                _fail("Unknown media company story", RpcCode.INVALID_ARGUMENT)
            return selected[0]["storyId"]
        if path == _READ:
            if request.storyId not in stories:
                _fail("Unknown media Story identity", RpcCode.INVALID_ARGUMENT)
            return request.storyId
        if path in (_EVENT, _EXTRA):
            field, table = (("eventStoryId", "EventStory") if path == _EVENT
                            else ("extraStoryId", "ExtraStory"))
            master = self.catalog.ids(table, required=True).get(getattr(request, field))
            if master is None or request.episode <= 0:
                _fail("Unknown media story episode", RpcCode.INVALID_ARGUMENT)
            if path == _EXTRA:
                # Share the menu's master validation without constructing and
                # discarding every part/story/episode DTO for one read.
                selected = [identity for number, identity in self._extras()[1][request.extraStoryId]
                            if number == request.episode]
                if len(selected) != 1:
                    _fail("Unknown media story episode", RpcCode.INVALID_ARGUMENT)
                return selected[0]
            episodes = self._episodes(master)
        else:
            part = self.catalog.ids("StoryPart", required=True).get(request.storyPartId)
            if part is None:
                _fail("Unknown media story part", RpcCode.INVALID_ARGUMENT)
            chapters = part.get("chapters")
            if (not isinstance(chapters, list)
                    or any(not isinstance(row, dict) or type(row.get("chapter", 0)) is not int
                           or type(row.get("route", 0)) is not int for row in chapters)):
                _fail("Media story chapters are malformed")
            selected = [row for row in chapters if row.get("chapter", 0) == request.chapter
                        and row.get("route", 0) == request.route]
            if len(selected) != 1:
                _fail("Unknown media story chapter", RpcCode.INVALID_ARGUMENT)
            episodes = self._episodes(selected[0])
        selected = [episode for episode in episodes if episode["episode"] == request.episode]
        if len(selected) != 1:
            _fail("Unknown media story episode", RpcCode.INVALID_ARGUMENT)
        return selected[0]["storyId"]

    def handle(self, path, plain):
        if path not in _ROUTES or path not in self.schema.methods or self.catalog.directory is None:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except DecodeError:
            _fail("Malformed media story request", RpcCode.INVALID_ARGUMENT)
        if path in (_LIST_EVENT, _LIST_EXTRA):
            return self._lists(path).SerializeToString()
        identity = self._resolve(path, request)
        result = self.schema.response_type(path)()

        def update(raw):
            try:
                snapshot = self.schema.response_type(_USER).FromString(raw)
            except DecodeError:
                _fail("Media profile snapshot is malformed")
            if not snapshot.HasField("user"):
                _fail("Media profile has no user state")
            if path == _COMPANY and request.characterId not in {row.characterId for row in snapshot.characters}:
                _fail("The media company character is not owned", RpcCode.PERMISSION_DENIED)
            matches = [row for row in snapshot.stories if row.storyId == identity]
            if len(matches) > 1:
                _fail("Media story state has ambiguous identities")
            story = matches[0] if matches else None
            if story is not None and (story.isInvalid or story.statusType not in (1, 2)):
                _fail("Media story state must be unlocked before playback")
            changed = story is None or (path != _RELEASE and story.statusType != 2)
            if story is None:
                story = snapshot.stories.add(storyId=identity, statusType=1)
            if path != _RELEASE:
                story.statusType = 2
            result.commonResponse.updatedData.stories.add().CopyFrom(story)
            result.commonResponse.deletedData.SetInParent()
            # No reward response or balance delta in local media mode.
            return snapshot.SerializeToString() if changed else raw

        try:
            self.state.mutate_snapshot(self.profile, self.schema.fingerprint, update)
        except ValueError:
            _fail("Media story progress cannot be updated with this schema")
        return result.SerializeToString()
