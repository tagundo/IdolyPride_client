"""Read-only Company screens for an explicitly separate media account.

Original 6.1.1 CompanyWindow.UpdateInfoAsync calls Company.TopAsync and keeps
the returned grade list/current rank (0x536ef70, 0x536c8dc). These reads expose
real master rows and already stored missions without reporting missions,
claiming rewards, inventing receipt history or calculating monthly salaries.
The ordinary account path is deliberately left to its existing provider.
"""
from __future__ import annotations

from google.protobuf.message import DecodeError

from .appearance import _owned
from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure


_USER = "/api.User/Get"
_TOP = "/api.Company/Top"
_ENJOY = "/api.Company/EnjoyCharacterTop"
_ROUTES = frozenset((_TOP, _ENJOY))
_MAX = (1 << 63) - 1


def _fail(reason, code=RpcCode.FAILED_PRECONDITION):
    raise RpcFailure(code, "Local media Company: " + reason)


def _number(value):
    if type(value) not in (int, str):
        _fail("invalid master point threshold")
    try:
        number = int(value)
    except (ValueError, OverflowError):
        _fail("invalid master point threshold")
    if not 0 <= number <= _MAX or isinstance(value, str) and str(number) != value:
        _fail("invalid master point threshold")
    return number


def _levels(catalog, table):
    result = {}
    for row in catalog.rows(table, required=True):
        key = row.get("levelKey")
        if type(key) is not int or not 0 < key <= (1 << 31) - 1 or key in result:
            _fail("invalid or duplicate master level: " + table)
        _number(row.get("requiredPoint"))
        result[key] = row
    return result


def _prepare_catalog(catalog):
    grades = catalog.ids("CompanyGrade", required=True)
    for row in grades.values():
        _number(row.get("requiredPoint"))
    trust = _levels(catalog, "CompanyTrustLevel")
    enjoy = _levels(catalog, "CompanyEnjoyCharacterLevel")
    characters = catalog.ids("Character", required=True)
    settings = {}
    for row in catalog.rows("CompanyEnjoyCharacterLevelSetting", required=True):
        character, level = row.get("characterId"), row.get("levelKey")
        if (not isinstance(character, str) or character not in characters
                or type(level) is not int or level not in enjoy
                or not isinstance(row.get("achieveRewardId"), str)
                or not row["achieveRewardId"]):
            _fail("invalid Company character/level master reference")
        levels = settings.setdefault(character, set())
        if level in levels:
            _fail("duplicate Company character/level master reference")
        levels.add(level)
    return grades, trust, settings, characters


def prepare_company_reads(master_dir):
    """Purely validate Company catalog joins before a media DB is changed.

    This reads the four Company JSON tables and the existing Character table;
    it has no State, filesystem write, clock, reward or session access. Runtime
    providers remain lazy so unrelated minimal Application fixtures work.
    """
    return _prepare_catalog(_Catalog(master_dir))


class CompanyReads:
    """Serve Top/EnjoyCharacterTop only when media mode is explicitly enabled.

    Every reward flag is false: this gallery has no Company reward receipt or
    claim provider. Rank zero is unranked, and monthly salary is unavailable
    (zero); cumulative UserCompany points are neither replaced nor recalculated.
    Mission lists contain only existing UserMission records. No request flag
    triggers automatic mission reporting or a snapshot/session write.
    """

    def __init__(self, schema, state, profile, master_dir=None, *, media_mode=False):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)
        self.media_mode = media_mode is True
        self._definitions = None

    def _prepare(self):
        if self._definitions is None:
            self._definitions = _prepare_catalog(self.catalog)
        return self._definitions

    def _snapshot(self):
        stored = self.state.snapshot(self.profile)
        if stored is None or stored[1] != self.schema.fingerprint:
            _fail("profile has no snapshot for this schema")
        try:
            snapshot = self.schema.response_type(_USER).FromString(stored[0])
        except DecodeError:
            _fail("profile snapshot is malformed")
        if not snapshot.HasField("user"):
            _fail("profile has no user state")
        if any(getattr(snapshot.company, field) < 0
               for field in ("enjoyPoint", "trustPoint", "salaryPoint")):
            _fail("stored Company points are malformed")
        return snapshot

    def _missions(self, snapshot, destination, *, character=None):
        masters = self.catalog.ids("Mission", required=True)
        categories = {key: destination.add(categoryType=key)
                      for key in range(1, 5 if character is None else 4)}
        seen = set()
        for mission in snapshot.missions:
            if not mission.missionId or mission.missionId in seen:
                _fail("stored mission identities are malformed")
            seen.add(mission.missionId)
            master = masters.get(mission.missionId)
            if master is None:
                continue
            if character is None:
                category = master.get("companyTrustMissionCategoryType", 0)
            else:
                if master.get("companyEnjoyCharacterId") != character:
                    continue
                category = master.get("companyEnjoyCharacterMissionCategoryType", 0)
            if type(category) is not int or category not in categories:
                continue
            progresses = master.get("progresses")
            if (not isinstance(progresses, list)
                    or not any(isinstance(row, dict)
                               and _number(row.get("threshold")) == mission.currentThreshold
                               for row in progresses)):
                _fail("stored Company mission threshold has no master reference")
            categories[category].userMissions.add().CopyFrom(mission)

    def handle(self, path, plain):
        if (not self.media_mode or path not in _ROUTES or path not in self.schema.methods
                or self.catalog.directory is None):
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except DecodeError:
            _fail("malformed request", RpcCode.INVALID_ARGUMENT)
        grades, trust, settings, characters = self._prepare()
        snapshot = self._snapshot()
        result = self.schema.response_type(path)()
        if path == _TOP:
            for key, row in sorted(grades.items(), key=lambda entry: (_number(entry[1]["requiredPoint"]), entry[0])):
                result.companyGradeInfos.add(id=key, isReceivable=False, isAlreadyReceived=False)
            for key in sorted(trust):
                result.trustLevelInfos.add(levelKey=key, isReceivable=False, isAlreadyReceived=False)
            self._missions(snapshot, result.trustMissionInfos)
        else:
            if not request.characterId or request.characterId not in characters:
                _fail("unknown Company character", RpcCode.INVALID_ARGUMENT)
            if request.characterId not in _owned(snapshot.characters, "characterId"):
                _fail("Company character is not owned", RpcCode.PERMISSION_DENIED)
            levels = settings.get(request.characterId)
            # Original CompanyEnjoyCharacterModel.CharacterId (0x536cfd0)
            # calls First(LevelInfos). Main-character UI filters non-normal
            # characters; direct unsupported requests must not return an
            # empty success that would fail in that original model.
            if not levels:
                _fail("character has no original Company level settings")
            for level in sorted(levels):
                result.enjoyLevelInfos.add(characterId=request.characterId, levelKey=level,
                                          isReceivable=False, isAlreadyReceived=False)
            self._missions(snapshot, result.missionInfos, character=request.characterId)
        # This provider only projects stored state; no user-data delta needs
        # to be constructed or applied by the original client.
        result.commonResponse.SetInParent()
        return result.SerializeToString()
