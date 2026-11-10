"""Complete or skip an audited public story once, preserving profile progress.

6.1.1 sends isLast=!isSkip; both values are legitimate completion paths.
Only the pinned 425-story public catalog is supported. Its 143 empty rewards
and 282 exact free-Stone-30 rewards have no Message/Telephone ReadStory
dependency in the pinned master. General story release and narrative schedules
remain separate features. No captured account totals are copied.
"""
from __future__ import annotations

from pathlib import Path

from google.protobuf.message import DecodeError

from . import story_read_rules as rules
from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure
from .story_catalog import StoryCatalog
from .tutorial_progression import _number


_USER = "/api.User/Get"
_READ = "/api.Story/Read"
_EVENT = "/api.Story/ReadEvent"
_EXTRA = "/api.Story/ReadExtra"
_LIST_EVENT = "/api.Story/ListEvent"
_LIST_EXTRA = "/api.Story/ListExtra"
_HOME = "/api.Home/Enter"
_STONE_REWARD = "rd_auto;stone;;30"
_MAX_INT32 = (1 << 31) - 1


def _fail(message, code=RpcCode.FAILED_PRECONDITION):
    raise RpcFailure(code, message)


def _one(rows, key, identity, *, label):
    matches = [row for row in rows if getattr(row, key) == identity]
    if len(matches) > 1:
        _fail("Ambiguous local story " + label)
    return matches[0] if matches else None


def _private_story_permissions(schema, fixtures, path):
    """Reconcile all captured variants using only their eligibility DTOs.

    A request digest does not identify the active account state. Conflicting
    captures therefore fail closed; ordering and unrelated account updates do
    not affect permission equivalence. Explicit empty variants remain decisive.
    """
    if fixtures is None or path not in schema.methods:
        return None
    source_path, field = path, "infos"
    variants = fixtures.variants(path)
    if not variants and path == _LIST_EXTRA:
        if (_HOME not in schema.methods or "extraStoryPartInfos" not in
                schema.response_type(_HOME).DESCRIPTOR.fields_by_name):
            return None
        source_path, field = _HOME, "extraStoryPartInfos"
        variants = fixtures.variants(_HOME)
    if not variants:
        return None

    def ordered(rows, key):
        values = [getattr(row, key) for row in rows]
        if (len(set(values)) != len(values)
                or any(value <= 0 if key == "episode" else not value for value in values)):
            _fail("Account story permission fixture has ambiguous identities")
        return sorted(rows, key=lambda row: getattr(row, key))

    expected = None
    for raw in variants:
        try:
            captured = schema.response_type(source_path).FromString(raw)
        except DecodeError:
            _fail("Account story permission fixture is malformed")
        result = schema.response_type(path)()
        for source in ordered(getattr(captured, field), "id"):
            info = result.infos.add(id=source.id)
            if path == _LIST_EXTRA:
                info.unlocked = source.unlocked
                episode_groups = []
                for source_story in ordered(source.stories, "id"):
                    story = info.stories.add(id=source_story.id, unlocked=source_story.unlocked)
                    episode_groups.append((source_story.episodes, story.episodes))
            else:
                episode_groups = [(source.episodes, info.episodes)]
            for source_episodes, episodes in episode_groups:
                for episode in ordered(source_episodes, "episode"):
                    episodes.add(episode=episode.episode, unlocked=episode.unlocked)
        result.commonResponse.updatedData.SetInParent()
        result.commonResponse.deletedData.SetInParent()
        projected = result.SerializeToString(deterministic=True)
        if expected is not None and expected != projected:
            _fail("Account story permission fixture variants disagree")
        expected = projected
    return expected


class StoryReads:
    def __init__(self, schema, state, profile, master_dir: Path | None = None, *,
                 story_catalog=None, fixtures=None, extra_fixture=None, event_fixture=None):
        self.schema, self.state, self.profile = schema, state, profile
        self.master_dir = Path(master_dir) if master_dir is not None else None
        self.catalog = _Catalog(self.master_dir)
        self.public = story_catalog if story_catalog is not None else StoryCatalog(schema, master_dir)
        self.fixtures, self.extra_fixture = fixtures, extra_fixture
        self.event_fixture = event_fixture

    def _version(self):
        if self.schema.fingerprint != rules.SCHEMA_SHA256 or self.catalog.version() != rules.MASTER_VERSION:
            _fail("Story read rules require their audited schema and master version")

    def _list(self, path):
        # Resolve the profile override inside the snapshot transaction. b'' is
        # authoritative empty eligibility, not a signal to use public defaults.
        callback = self.extra_fixture if path == _LIST_EXTRA else self.event_fixture
        raw = callback() if callback is not None else None
        if raw is None:
            raw = _private_story_permissions(self.schema, self.fixtures, path)
        if raw is None:
            raw = self.public.handle(path, b"")
        if raw is None:
            _fail("Local story eligibility catalog is unavailable")
        if not isinstance(raw, bytes):
            _fail("Local story eligibility catalog is malformed")
        try:
            return self.schema.response_type(path).FromString(raw)
        except DecodeError:
            _fail("Local story eligibility catalog is malformed")

    def _event_allowed(self, identity, number):
        info = _one(self._list(_LIST_EVENT).infos, "id", identity, label="event eligibility")
        if info is None:
            return False
        episode = _one(info.episodes, "episode", number, label="event episode eligibility")
        return episode is not None and episode.unlocked

    def _extra_allowed(self, identity, number, part_id):
        part = _one(self._list(_LIST_EXTRA).infos, "id", part_id, label="extra part eligibility")
        if part is None or not part.unlocked:
            return False
        info = _one(part.stories, "id", identity, label="extra story eligibility")
        if info is None or not info.unlocked:
            return False
        episode = _one(info.episodes, "episode", number, label="extra episode eligibility")
        return episode is not None and episode.unlocked

    @staticmethod
    def _episodes(master):
        episodes = master.get("episodes")
        if not isinstance(episodes, list) or any(not isinstance(row, dict) for row in episodes):
            _fail("Local story master episodes are malformed")
        numbers = [row.get("episode") for row in episodes]
        if any(type(value) is not int or value <= 0 for value in numbers) or len(set(numbers)) != len(numbers):
            _fail("Local story master episodes are ambiguous")
        if any(not isinstance(row.get("storyId"), str) or not row["storyId"] for row in episodes):
            _fail("Local story episode has no Story reference")
        return episodes

    @staticmethod
    def _episode(master, number):
        episodes = StoryReads._episodes(master)
        found = next((row for row in episodes if row["episode"] == number), None)
        if found is None:
            _fail("Requested story episode does not exist", RpcCode.INVALID_ARGUMENT)
        identity = found.get("storyId")
        if not isinstance(identity, str) or not identity:
            _fail("Local story episode has no Story reference")
        return identity

    def _extra_master(self, identity):
        master = self.catalog.ids("ExtraStory", required=True).get(identity)
        if master is None:
            _fail("Unknown extra story identity", RpcCode.INVALID_ARGUMENT)
        part_id = master.get("extraStoryPartId")
        part = self.catalog.ids("ExtraStoryPart", required=True).get(part_id)
        links = part.get("extraStoryIds") if part is not None else None
        if (not isinstance(links, list) or any(not isinstance(value, str) or not value for value in links)
                or len(set(links)) != len(links) or identity not in links):
            _fail("Local extra story parent link is invalid")
        return master, part_id

    def _resolve(self, path, request):
        if path == _EVENT:
            if not request.eventStoryId or request.episode <= 0:
                _fail("An event identity and positive episode are required", RpcCode.INVALID_ARGUMENT)
            master = self.catalog.ids("EventStory", required=True).get(request.eventStoryId)
            if master is None:
                _fail("Unknown event story identity", RpcCode.INVALID_ARGUMENT)
            identity = self._episode(master, request.episode)
            return identity, lambda: self._event_allowed(request.eventStoryId, request.episode)
        if path == _EXTRA:
            if not request.extraStoryId or request.episode <= 0:
                _fail("An extra story identity and positive episode are required", RpcCode.INVALID_ARGUMENT)
            master, part_id = self._extra_master(request.extraStoryId)
            identity = self._episode(master, request.episode)
            return identity, lambda: self._extra_allowed(request.extraStoryId, request.episode, part_id)
        if not request.storyId:
            _fail("A Story identity is required", RpcCode.INVALID_ARGUMENT)
        identity = request.storyId
        # A direct Read must honor exactly the same public/profile eligibility;
        # it cannot bypass a locked parent by addressing the leaf Story ID.
        def allowed():
            for parent in self.catalog.ids("EventStory", required=True).values():
                for episode in self._episodes(parent):
                    if episode.get("storyId") == identity and self._event_allowed(parent["id"], episode["episode"]):
                        return True
            for parent in self.catalog.ids("ExtraStory", required=True).values():
                for episode in self._episodes(parent):
                    if episode.get("storyId") == identity:
                        _, part_id = self._extra_master(parent["id"])
                        if self._extra_allowed(parent["id"], episode["episode"], part_id):
                            return True
            return False
        return identity, allowed

    def _reward(self, identity):
        master = self.catalog.ids("Story", required=True).get(identity)
        if master is None:
            _fail("Unknown Story identity", RpcCode.INVALID_ARGUMENT)
        reward = master.get("rewardId", "")
        if identity in rules.NO_REWARD_STORIES and reward == "":
            return 0
        if identity in rules.FREE_STONE_STORIES and reward == _STONE_REWARD:
            return 30
        _fail("This story read or reward rule is not implemented", RpcCode.UNIMPLEMENTED)

    def _stone_total(self, snapshot, amount):
        rows = self.catalog.rows("Setting", required=True)
        if len(rows) != 1:
            _fail("Story rewards need one Setting master row")
        before = _number(snapshot.balance.freeBalance, "free Stone balance")
        after = _number(before + amount, "free Stone balance")
        limit = _number(rows[0].get("freeStoneLimit"), "free Stone limit", positive=True)
        if after > min(limit, _MAX_INT32):
            _fail("Story reward would exceed the local free Stone limit")
        return before, after

    def handle(self, path, plain):
        if path not in (_READ, _EVENT, _EXTRA) or self.master_dir is None or path not in self.schema.methods:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except DecodeError:
            _fail("Malformed story read request", RpcCode.INVALID_ARGUMENT)
        result = self.schema.response_type(path)()

        def update(raw):
            self._version()
            identity, allowed = self._resolve(path, request)
            reward = self._reward(identity)
            if not allowed():
                _fail("The requested story episode is not unlocked", RpcCode.PERMISSION_DENIED)
            try:
                snapshot = self.schema.response_type(_USER).FromString(raw)
            except DecodeError:
                _fail("Local profile snapshot is malformed")
            if not snapshot.HasField("user"):
                _fail("Local profile has no user state")
            story = _one(snapshot.stories, "storyId", identity, label="profile progress")
            if story is not None and (story.isInvalid or story.statusType not in (1, 2)):
                _fail("The requested profile story is unavailable", RpcCode.PERMISSION_DENIED)
            already_read = story is not None and story.statusType == 2
            before_after = self._stone_total(snapshot, reward) if reward and not already_read else None
            # All permission, master and wallet checks finish before mutation.
            if not already_read:
                if story is None:
                    story = snapshot.stories.add(storyId=identity)
                story.statusType = 2
                if before_after is not None:
                    before, after = before_after
                    snapshot.balance.freeBalance = after
                    result.rewards.add(resourceType=15, resourceId="", beforeAmount=before,
                                       afterAmount=after, amountI64=reward)
            result.commonResponse.updatedData.stories.add().CopyFrom(story)
            result.commonResponse.deletedData.SetInParent()
            if reward:
                # Repeated requests re-project the current wallet, not the old
                # first-read total, and never emit another earned reward.
                _number(snapshot.balance.freeBalance, "free Stone balance")
                result.commonResponse.updatedData.balance.CopyFrom(snapshot.balance)
            return raw if already_read else snapshot.SerializeToString()

        try:
            self.state.mutate_snapshot(self.profile, self.schema.fingerprint, update)
        except ValueError:
            _fail("Local story progress cannot be updated with this schema")
        return result.SerializeToString()
