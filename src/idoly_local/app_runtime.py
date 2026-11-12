"""Shared embedded runtime for the Android server APK and macOS server app.

This entry point imports no grpcio code. Both native launchers run the same
Application engine over the pure-Python HTTP/2 transport and local asset server.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
import threading


class _StartupSettings:
    def __init__(self, value):
        self._value = dict(value)

    def settings(self):
        return dict(self._value)


class Runtime:
    """Own listeners, threads and a bounded log for one embedded server instance."""

    def __init__(self, profile: str, log_callback=None):
        self.profile = profile
        self._callback = log_callback
        self._logs = deque(maxlen=200)
        self._log_lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._grpc = None
        self._asset = None
        self._asset_thread = None
        self._asset_started = False
        self._resources = None
        self._running = False
        self._stopped = False
        self._last_error = None
        self._experimental_main_live = False
        self._media_mode = False
        self._presentation = None
        self._playback = None
        self._render_probe = None
        self._wardrobe_probe = None
        self._media_settings = None
        self._language_settings = None
        self._library = None
        self._active_media = None
        self._effective_language = None
        self._grpc_address = None
        self._asset_url = None
        from .diagnostics import ClientDiagnostics
        self._diagnostics = ClientDiagnostics(self._log)
        self._transfer_lock = threading.Lock()
        self._transfers = {}
        self._transfer_status = {"active_requests": 0, "path": "", "sent_bytes": 0,
                                 "total_bytes": 0, "status": "idle", "http_status": 0,
                                 "completed_requests": 0, "failed_requests": 0,
                                 "session_bytes_sent": 0}

    def _log(self, message):
        # Transport logging contains method paths and fixed diagnostic messages,
        # never protobuf request bodies or authentication metadata.
        line = str(message).replace("\r", " ").replace("\n", " ")[:2000]
        with self._log_lock:
            self._logs.append(line)
        if self._callback is not None:
            try:
                self._callback(line)
            except Exception:
                # A UI callback cannot own or terminate the serving threads.
                pass

    def status(self) -> dict:
        """Return a JSON-serializable snapshot for either native launcher's UI."""
        with self._lifecycle_lock:
            result = {"running": self._running, "profile": self.profile,
                      "grpc_address": self._grpc_address, "asset_url": self._asset_url,
                      "last_error": self._last_error}
            result["media_mode"] = self._media_mode
            if self._experimental_main_live:
                result["experimental_main_live"] = True
                result["live_ruleset"] = "live-v5"
            library = self._library
        with self._log_lock:
            result["logs"] = list(self._logs)
        diagnostics = self._diagnostics.status()
        result["client_diagnostics"] = {key: value for key, value in diagnostics.items() if key != "events"}
        with self._transfer_lock:
            result["asset_transfer"] = dict(self._transfer_status)
        if self._resources is not None:
            result["resource_transfer"] = self._resources.status()
        if self._presentation is not None:
            result["presentation"] = self._presentation.status()
        if self._playback is not None:
            result["playback"] = self._playback.status()
        if self._render_probe is not None:
            result["render_probe"] = self._render_probe.status()
        if self._wardrobe_probe is not None:
            result["wardrobe_probe"] = self._wardrobe_probe.status()
        if self._media_settings is not None:
            result["media_options"] = self._media_settings.status()
            if self._active_media is not None:
                result["media_options"]["effective_settings"] = self._active_media.settings()
        if self._language_settings is not None:
            result["language"] = self._language_settings.status()
            result["language"]["effective_language"] = self._effective_language
        if library is not None:
            result["resource_library"] = library.status()
        return result

    def diagnostics_snapshot(self) -> dict:
        """Export only safe runtime observations, never profiles or credentials."""
        return {"schema": 1, "runtime": self.status(),
                "client_diagnostics": self._diagnostics.status()}

    def _observe_transfer(self, event):
        with self._transfer_lock:
            key, phase = event["transfer_id"], event["phase"]
            previous = self._transfers.get(key, 0)
            sent = event["sent_bytes"]
            self._transfer_status["session_bytes_sent"] += max(0, sent - previous)
            self._transfers[key] = sent
            if phase in ("completed", "failed"):
                self._transfers.pop(key, None)
                counter = "completed_requests" if phase == "completed" else "failed_requests"
                self._transfer_status[counter] += 1
            self._transfer_status.update(active_requests=len(self._transfers), path=event["path"],
                                         sent_bytes=sent, total_bytes=event["total_bytes"],
                                         status=phase, http_status=event["http_status"])
        if phase in ("completed", "failed"):
            word = "완료" if phase == "completed" else "중단"
            self._log(f"마스터 파일 전송 {word}: {event['path']} · {sent}/{event['total_bytes']} 바이트")

    def stop(self):
        """Stop both listeners and release their ports; repeated calls are safe."""
        with self._lifecycle_lock:
            if self._stopped:
                return
            self._running = False
            failures = []
            if self._library is not None:
                try:
                    self._library.close()
                    self._library = None
                except Exception as error:
                    failures.append(error)
            if self._grpc is not None:
                try:
                    self._grpc.stop()
                    self._grpc = None
                except Exception as error:
                    failures.append(error)
            if self._asset is not None:
                try:
                    gateway = getattr(self._asset, "octo_gateway", None)
                    if gateway is not None:
                        gateway.close()
                    if self._asset_started:
                        self._asset.shutdown()
                    self._asset.server_close()
                    if self._asset_thread is not None and self._asset_thread is not threading.current_thread():
                        self._asset_thread.join(timeout=5)
                        if self._asset_thread.is_alive():
                            raise RuntimeError("Asset server thread did not stop")
                    self._asset = None
                    self._asset_thread = None
                    self._asset_started = False
                except Exception as error:
                    failures.append(error)
            self._stopped = not failures
            if failures:
                self._last_error = "Server cleanup failed; retry Stop"
                self._running = bool(
                    (self._grpc is not None and self._grpc.running)
                    or (self._asset_thread is not None and self._asset_thread.is_alive())
                )
            else:
                self._last_error = None
        if failures:
            self._log(self._last_error)
            raise RuntimeError(self._last_error) from failures[0]
        self._log("Local server stopped")


def start(data_dir, profile="sandbox", log_callback=None, *,
          grpc_host="127.0.0.1", grpc_port=50051,
          asset_host="127.0.0.1", asset_port=8080, aes_cbc=None,
          experimental_main_live=False, live_engine_library=None,
          download_missing_resources=True, resource_fetcher=None, media_mode=False,
          resource_platform="android", resource_cache_dir=None) -> Runtime:
    """Start the local game engine and asset server without blocking the UI.

    ``data_dir`` contains ``protocol/idolypride-6.1.1.pb`` and
    ``original-master/{master-tag.json,assets/master/*}``, plus the curated
    ``master-json/`` catalog used by the game engine. A local ``state.db``
    and optional ``fixtures/`` live beside those bundles. Existing profile
    snapshots are preserved. Port zero is available for lifecycle tests.

    ``aes_cbc``, when supplied, configures the launcher's Java AES bridge before
    the engine is imported. An already configured backend is preserved when it
    is omitted. The macOS launcher uses the normal Python AES backend.
    """
    if type(experimental_main_live) is not bool:
        raise ValueError("Experimental main live must be an explicit boolean")
    if type(download_missing_resources) is not bool:
        raise ValueError("Resource downloads must be an explicit boolean")
    if type(media_mode) is not bool:
        raise ValueError("Media mode must be an explicit boolean")
    from .octo_runtime import _platform_archive
    _platform_archive(resource_platform)
    if resource_fetcher is not None and not callable(resource_fetcher):
        raise ValueError("Resource fetcher must be callable")
    if resource_cache_dir is not None:
        resource_cache_dir = Path(resource_cache_dir)
        if not resource_cache_dir.is_absolute() or resource_cache_dir.is_symlink():
            raise ValueError("Resource cache directory must be an absolute regular directory")
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("A nonempty local profile is required")
    if log_callback is not None and not callable(log_callback):
        raise ValueError("Log callback must accept one message string")
    root = Path(data_dir).resolve()
    runtime = Runtime(profile, log_callback)
    runtime._media_mode = media_mode
    from .presentation import PresentationState
    runtime._presentation = PresentationState(root / "client-presentation.json")
    from .playback import PlaybackState
    runtime._playback = PlaybackState(root / "client-playback.json")
    from .render_probe import RenderProbeState
    runtime._render_probe = RenderProbeState()
    from .wardrobe_diagnostics import WardrobeDiagnostics
    runtime._wardrobe_probe = WardrobeDiagnostics(runtime._log)
    from .media_settings import MediaSettingsState
    runtime._media_settings = MediaSettingsState(root / "client-media.json")
    from .language_settings import LanguageSettingsState
    runtime._language_settings = LanguageSettingsState(root / "client-language.json")
    runtime._active_media = _StartupSettings(runtime._media_settings.settings())
    runtime._effective_language = runtime._language_settings.settings()["language"]
    try:
        # Imports stay inside startup so launchers can extract bundled data and
        # configure their platform's codec before loading the application engine.
        if aes_cbc is not None:
            from .codec import configure_aes
            configure_aes(aes_cbc)
        from .application import Application
        from .assets import create_asset_server, prepare_master_tag, select_master_tag
        from .catalog import FixtureStore
        from .h2_server import create_server
        from .gameplay import (repair_starter_home_positions, repair_starter_inventory,
                               repair_starter_roster, repair_starter_card_level_mission,
                               seed_starter_profile)
        from .schema import Schema
        from .state import State

        master_dir = root / "master-json"
        if not master_dir.is_dir():
            raise ValueError("Bundled master-json catalog is missing")
        schema = Schema.from_descriptor_set(root / "protocol" / "idolypride-6.1.1.pb")
        archive = root / "original-master"
        master_tag = select_master_tag(archive / "master-tag.json", media_mode=media_mode)
        from .language_settings import select_language_tag
        master_tag = select_language_tag(master_tag, runtime._effective_language)
        from .master_sort import select_sorted_master_tag
        master_tag = select_sorted_master_tag(master_tag, runtime._active_media.settings())
        if media_mode:
            # Detect incomplete/invalid media data before inventory seeding.
            # The final response is rebased to the bound HTTP port below.
            prepare_master_tag(schema, master_tag, archive / "assets" / "master", "http://127.0.0.1")
        state = State(root / ("media-state.db" if media_mode else "state.db"))
        media_scenes = None
        if media_mode:
            from .media_runtime import prepare_media_profile
            media_scenes = prepare_media_profile(state, schema, profile, master_dir)
            runtime._log("감상용 전체 해금 프로필을 준비했습니다.")
        elif state.snapshot(profile) is None:
            seed_starter_profile(state, schema, profile, master_dir)
            runtime._log("Created local profile " + profile)
        else:
            if repair_starter_roster(state, schema, profile, master_dir):
                runtime._log("홈 표시용 기본 캐릭터 데이터를 보완했습니다.")
            if repair_starter_home_positions(state, schema, profile, master_dir):
                runtime._log("기본 홈 배치의 중복 캐릭터를 보완했습니다.")
            if repair_starter_inventory(state, schema, profile, master_dir):
                runtime._log("기본 카드·아이템과 유닛 편성을 준비했습니다.")
            if repair_starter_card_level_mission(state, schema, profile, master_dir):
                runtime._log("기본 카드 레벨 달성 미션을 준비했습니다.")
            runtime._log("Loaded local profile " + profile)
        runtime._asset = create_asset_server(asset_host, asset_port, archive / "assets",
                                             diagnostics=runtime._diagnostics,
                                             transfer_callback=runtime._observe_transfer,
                                             runtime_status_callback=runtime.diagnostics_snapshot,
                                             presentation=runtime._presentation, playback=runtime._playback,
                                             render_probe=runtime._render_probe,
                                             media_settings=runtime._active_media,
                                             wardrobe_probe=runtime._wardrobe_probe)
        bound_asset_host, bound_asset_port = runtime._asset.server_address[:2]
        # The two apps serve on their own loopback interface. A wildcard bind,
        # if selected for diagnostics, must still advertise a concrete address.
        asset_url_host = "127.0.0.1" if bound_asset_host in ("0.0.0.0", "") else bound_asset_host
        if ":" in asset_url_host:
            asset_url_host = "[" + asset_url_host + "]"
        runtime._asset_url = f"http://{asset_url_host}:{bound_asset_port}"
        from .octo_runtime import create_octo_gateway
        gateway, runtime._resources = create_octo_gateway(
            root, runtime._asset_url, aes_cbc=aes_cbc, fetcher=resource_fetcher,
            allow_downloads=download_missing_resources, log_callback=runtime._log,
            platform=resource_platform, resource_cache_dir=resource_cache_dir)
        # Install the gateway only after binding has selected the actual port,
        # and before any HTTP serving thread is started.
        runtime._asset.octo_gateway = gateway
        from .resource_library import ResourceLibrary
        runtime._library = ResourceLibrary.from_data_dir(root, base_url=runtime._asset_url,
            aes_cbc=aes_cbc, fetcher=resource_fetcher, active_gateway=gateway,
            resource_cache_dir=resource_cache_dir)
        if resource_cache_dir is not None:
            runtime._log("게임 리소스를 선택한 Downloads 보관 폴더에서 직접 제공합니다.")
        # Installed before any serving thread starts, just like the gateway.
        # The handler reads this bound attribute for export/status commands.
        runtime._asset.resource_library = runtime._library
        master_response = prepare_master_tag(schema, master_tag,
                                             archive / "assets" / "master", runtime._asset_url)
        if media_mode:
            runtime._log("감상 촬영용 의상 제한 해제 마스터를 제공합니다.")
        fixtures = FixtureStore(root / ("media-fixtures" if media_mode else "fixtures"), schema)
        live_options = {}
        if experimental_main_live:
            import sys
            from .live_engine import NativeLiveEngine
            if live_engine_library is None:
                library_name = "libidoly_live.dylib" if sys.platform == "darwin" else "libidoly_live.so"
                live_engine_library = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / library_name
            live_options = {"experimental_main_live": True,
                            "live_engine": NativeLiveEngine(Path(live_engine_library))}
        media_options = {"media_settings": runtime._active_media.settings}
        if media_mode:
            media_options.update(media_mode=True, photo_scene_access=media_scenes)
        application = Application(schema, state, fixtures, profile=profile, master_response=master_response,
                                  master_dir=master_dir, **media_options, **live_options)
        runtime._experimental_main_live = experimental_main_live
        if experimental_main_live:
            runtime._log("일반 라이브 실험 기능 사용: 첫 메인 퀘스트 · 로컬 계산 규칙")
        runtime._grpc = create_server(application, host=grpc_host, port=grpc_port, log_callback=runtime._log)
        runtime._grpc_address = f"{runtime._grpc.address[0]}:{runtime._grpc.address[1]}"
        runtime._asset_thread = threading.Thread(target=runtime._asset.serve_forever,
                                                  name=f"idoly-assets-{bound_asset_port}", daemon=True)
        runtime._asset_thread.start()
        runtime._asset_started = True
        runtime._grpc.start()
        runtime._running = True
        runtime._log("Local gRPC server ready at " + runtime._grpc_address)
        runtime._log("Local assets ready at " + runtime._asset_url)
        return runtime
    except Exception as error:
        runtime._last_error = "Startup failed: " + str(error)
        runtime._log(runtime._last_error)
        try:
            runtime.stop()
        except Exception:
            # Preserve the original startup reason while still attempting both
            # listener cleanups; stop retains resources whose cleanup failed.
            pass
        raise
