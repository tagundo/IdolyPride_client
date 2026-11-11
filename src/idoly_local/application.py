"""Shared game request handling for desktop and embedded mobile transports."""
from __future__ import annotations

import logging
from pathlib import Path
from google.protobuf.message import DecodeError
from . import codec
from .rpc import RpcCode
from .state import State
from .catalog import FixtureStore

LOG = logging.getLogger(__name__)

# 2100-01-01 UTC. The recovered title treats a zero refund start/end as
# unbounded, so zeros would expose the official refund flow. A future window
# keeps it inactive; shopInvalidStartDatetime=0 closes paid-shop entry.
LOCAL_REFUND_DATETIME_MS = 4102444800000


class Application:
    def __init__(self, schema, state: State, fixtures, profile="local", master_response: bytes | None = None,
                 master_dir=None, *, experimental_main_live=False, live_engine=None,
                 dream_catalog_path=None, pvp_catalog_path=None,
                 photo_scene_access=None, photo_image_urls=None):
        if type(experimental_main_live) is not bool:
            raise ValueError("Experimental main live must be an explicit boolean")
        self.schema = schema
        self.state = state
        self.fixtures = fixtures
        self.profile = profile
        self.master_response = master_response
        from .gameplay import Gameplay
        from .quest import Quest
        from .tutorial_replay import TutorialReplays
        from .tutorial_progression import TutorialProgression
        from .tutorial_messages import TutorialMessages
        from .lessons import OrdinaryLessons
        from .social import SocialInbox
        from .story_catalog import StoryCatalog
        from .story_reads import StoryReads
        from .appearance import Appearance
        from .profile_names import ProfileNames
        from .profile_messages import ProfileMessages
        from .profile_favorites import ProfileFavorites
        from .profile_top import ProfileTop
        from .card_level_missions import CardLevelMissions
        from .dream import Dream
        from .pvp import Pvp
        from .photo_shooting import PhotoShootings
        self.lessons = OrdinaryLessons(schema, state, profile, master_dir)
        self.social = SocialInbox(schema)
        self.stories = StoryCatalog(schema, master_dir)
        self.story_reads = StoryReads(schema, state, profile, master_dir, story_catalog=self.stories,
                                      fixtures=self.fixtures, extra_fixture=self._story_extra_fixture,
                                      event_fixture=self._story_event_fixture)
        self.appearance = Appearance(schema, state, profile, master_dir)
        self.profile_names = ProfileNames(schema, state, profile)
        self.profile_messages = ProfileMessages(schema, state, profile)
        self.profile_favorites = ProfileFavorites(schema, state, profile, master_dir)
        self.dream = Dream(schema, state, profile, master_dir, catalog_path=dream_catalog_path)
        self.pvp = Pvp(schema, state, profile, master_dir, catalog_path=pvp_catalog_path)
        self.photo_shootings = PhotoShootings(schema, state, profile, master_dir,
            scene_access=photo_scene_access, image_urls=photo_image_urls)
        self.main_lives = None
        if experimental_main_live:
            from .main_live import MainLives
            self.main_lives = MainLives(schema, state, profile, master_dir, engine=live_engine, enabled=True)
        self.gameplay = Gameplay(schema, state, profile, master_dir, lessons=self.lessons, stories=self.stories,
                                 story_extra_fixture=self._story_extra_fixture, dream=self.dream)
        self.profile_top = ProfileTop(schema, state, profile, self.gameplay.catalog)
        self.card_level_missions = CardLevelMissions(schema, state, profile, master_dir)
        self.tutorial_progression = TutorialProgression(schema, state, profile, master_dir)
        self.tutorial_messages = TutorialMessages(schema, state, profile, master_dir)
        self.tutorial_replays = TutorialReplays(schema, state, profile, master_dir)
        self.quest = Quest(schema, state, profile, master_dir, tutorial_replays=self.tutorial_replays,
                           pvp=self.pvp)
        self.public_fixtures = FixtureStore(Path(master_dir).parent / "public-fixtures", schema) if master_dir is not None else None

    def _story_extra_fixture(self):
        """Use the same account eligibility for Home, lists and read actions."""
        from .story_reads import _private_story_permissions
        return _private_story_permissions(self.schema, self.fixtures, "/api.Story/ListExtra")

    def _story_event_fixture(self):
        from .story_reads import _private_story_permissions
        return _private_story_permissions(self.schema, self.fixtures, "/api.Story/ListEvent")

    def handle(self, path, raw, context):
        method = self.schema.methods.get(path)
        if method is None or method.client_streaming or method.server_streaming:
            context.abort(RpcCode.UNIMPLEMENTED, "Unsupported local RPC method")
        # Deserialize here so malformed traffic maps to INVALID_ARGUMENT instead
        # of gRPC's generic INTERNAL serializer failure. Never log request bodies.
        try:
            plain = codec.decode(raw)
            self.schema.request_type(path).FromString(plain)
        except (ValueError, DecodeError):
            context.abort(RpcCode.INVALID_ARGUMENT, "Malformed encrypted protobuf request")
        response_type = self.schema.response_type(path)
        LOG.info("RPC %s", path)
        # Auth.Login deliberately ignores firebaseIDToken: this is a single local
        # profile, with no online token validation, refresh, or credential storage.
        if path == "/api.Auth/Login":
            token, profile = self.state.login(self.profile)
            result = response_type(gameAuthToken=token)
            result.userPublic.serverUserId = profile["server_id"]
            result.userPublic.publicUserId = profile["public_id"]
            return result.SerializeToString()
        if path == "/api.System/Check":
            result = response_type(keepAliveTimeMilliseconds=60000, keepAliveTimeoutMilliseconds=20000)
            result.maintenanceInfo.inMaintenance = False
            result.reviewInfo.inReview = False
            return result.SerializeToString()
        if path in ("/api.System/GetMetadata", "/api.System/CheckApp"):
            return response_type().SerializeToString()
        if path == "/api.Refund/GetTerm":
            # TitlePresenter calls this immediately after System.Check, before
            # Auth.Login. It is an anonymous schedule query, not account data.
            # Local profiles have no official cash purchase/refund operations.
            return response_type(startDatetime=LOCAL_REFUND_DATETIME_MS,
                                 endDatetime=LOCAL_REFUND_DATETIME_MS,
                                 shopInvalidStartDatetime=0).SerializeToString()
        # These title-screen text APIs are anonymous in the Toolkit's observed
        # official flow, and may be needed before a local login is possible.
        if path in ("/api.Master/Rule", "/api.Master/GetHelpCategory"):
            response = self.fixtures.get(path, plain)
            if response is None and self.public_fixtures is not None:
                response = self.public_fixtures.get(path, plain)
            if response is not None:
                return response
            context.abort(RpcCode.UNIMPLEMENTED, "No local text fixture for " + path)
        metadata = dict(context.invocation_metadata())
        if not self.state.authenticated(metadata.get("x-auth-token", ""), self.profile):
            context.abort(RpcCode.UNAUTHENTICATED, "Local Auth.Login is required")
        if path == "/api.Master/Get" and self.master_response is not None:
            return self.master_response
        response = self.fixtures.get(path, plain)
        if response is not None:
            return response
        if path == "/api.User/Get":
            snapshot = self.state.snapshot(self.profile)
            if snapshot is not None:
                payload, schema_sha256 = snapshot
                if schema_sha256 != self.schema.fingerprint:
                    context.abort(RpcCode.FAILED_PRECONDITION, "Profile snapshot uses a different schema; import it with the current schema")
                return payload
        from .rpc import RpcFailure
        try:
            if path in ("/api.Story/ListEvent", "/api.Story/ListExtra"):
                captured = (self._story_extra_fixture() if path == "/api.Story/ListExtra"
                            else self._story_event_fixture())
                if captured is not None:
                    return captured
            response = self.gameplay.handle(path, plain)
            if response is None:
                response = self.dream.handle(path, plain)
            if response is None:
                response = self.pvp.handle(path, plain)
            if response is None:
                response = self.photo_shootings.handle(path, plain)
            if response is None:
                response = self.lessons.handle(path, plain)
            if response is None:
                response = self.social.handle(path, plain)
            if response is None:
                response = self.stories.handle(path, plain)
            if response is None:
                response = self.story_reads.handle(path, plain)
            if response is None:
                response = self.appearance.handle(path, plain)
            if response is None:
                response = self.profile_names.handle(path, plain)
            if response is None:
                response = self.profile_messages.handle(path, plain)
            if response is None:
                response = self.profile_favorites.handle(path, plain)
            if response is None:
                response = self.profile_top.handle(path, plain)
            if response is None:
                response = self.card_level_missions.handle(path, plain)
            if response is None and self.main_lives is not None:
                request_ids = [value for key, value in context.invocation_metadata() if key == "x-app-request-id"]
                if path == "/api.Quest/Start" and len(request_ids) != 1:
                    raise RpcFailure(RpcCode.INVALID_ARGUMENT, "One x-app-request-id is required for a local live")
                response = self.main_lives.handle(path, plain,
                    request_id=request_ids[0] if len(request_ids) == 1 else None)
            if response is None:
                response = self.tutorial_progression.handle(path, plain)
            if response is None:
                response = self.tutorial_messages.handle(path, plain)
            if response is None:
                response = self.tutorial_replays.handle(path, plain)
            if response is None:
                response = self.quest.handle(path, plain)
        except RpcFailure as failure:
            context.abort(failure.code, failure.details)
        except ValueError:
            context.abort(RpcCode.FAILED_PRECONDITION, "Local profile or master catalog is not ready for this action")
        if response is not None:
            return response
        context.abort(RpcCode.UNIMPLEMENTED, "No local handler or response fixture for " + path)
