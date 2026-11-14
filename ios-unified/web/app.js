(function (root) {
  "use strict";

  const MAX_ID = 2147483647;
  const MAX_PENDING = 16;
  const ACTIVE_JOBS = new Set(["preparing", "running", "export_ready", "cancelling"]);
  const LANGUAGES = {ko: "한국어", ja: "日本語", en: "English"};
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const integer = value => Number.isSafeInteger(value) && value >= 0;
  const choice = (value, values) => values.includes(value);
  const exact = (value, keys) => object(value) && Object.keys(value).length === keys.length && keys.every(key => Object.prototype.hasOwnProperty.call(value, key));
  const identity = value => object(value) && value.schema === 1 && integer(value.revision);
  const validOptions = value => object(value) && typeof value.media_mode === "boolean" && typeof value.download_missing_resources === "boolean" && choice(value.language, ["ko", "ja", "en"]);
  const validPresentation = value => exact(value, ["schema", "revision", "custom_graphics", "quality", "target_fps", "render_scale", "max_buffer_pixel", "anti_aliasing", "shadow_resolution", "expand_photography"]) && identity(value) && typeof value.custom_graphics === "boolean" && typeof value.expand_photography === "boolean" && choice(value.quality, [0, 10, 20, 30, 40, 100]) && choice(value.target_fps, [0, 30, 60, 90, 120]) && typeof value.render_scale === "number" && Number.isFinite(value.render_scale) && value.render_scale >= 0.25 && value.render_scale <= 2 && integer(value.max_buffer_pixel) && value.max_buffer_pixel >= 256 && value.max_buffer_pixel <= 4096 && value.max_buffer_pixel % 2 === 0 && choice(value.anti_aliasing, [-1, 0, 1, 2]) && choice(value.shadow_resolution, [0, 512, 1024, 2048, 4096]);
  const validPlayback = value => exact(value, ["schema", "revision", "wait_for_orientation"]) && identity(value) && typeof value.wait_for_orientation === "boolean";
  const validMedia = value => exact(value, ["schema", "revision", "hide_video_mv", "mv_sort", "outfit_sort"]) && identity(value) && typeof value.hide_video_mv === "boolean" && choice(value.mv_sort, ["recent", "old", "title", "id"]) && choice(value.outfit_sort, ["original", "recent", "old", "title", "id"]);
  const plain = (value, limit = 1000) => typeof value === "string" ? value.slice(0, limit) : "";
  const count = value => integer(value) ? value : 0;
  const boundedJSON = (value, limit) => {
    try { const encoded = JSON.stringify(value); return typeof encoded === "string" && encoded.length <= limit; }
    catch (_) { return false; }
  };

  function validRequest(action, payload) {
    if (action === "status") return exact(payload, []);
    if (action === "save_options") return exact(payload, ["media_mode", "download_missing_resources", "language"]) && validOptions(payload);
    if (action === "save_presentation") return exact(payload, ["settings"]) && validPresentation(payload.settings);
    if (action === "save_playback") return exact(payload, ["settings"]) && validPlayback(payload.settings);
    if (action === "save_media") return exact(payload, ["settings"]) && validMedia(payload.settings);
    if (action === "resources_cancel") return exact(payload, ["job_id"]) && typeof payload.job_id === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(payload.job_id);
    if (action === "resources_download") return exact(payload, ["parallelism"]) && choice(payload.parallelism, [1, 2, 4, 8]);
    if (["resources_preview", "resources_import", "resources_export"].includes(action)) return exact(payload, []);
    return false;
  }

  // The only transport is the native handler. IDs are never reused in a page,
  // so a reply arriving after hide, timeout or a later request cannot own it.
  function createBridge(scope, timers = scope) {
    const pending = new Map();
    const listeners = new Set();
    let nextID = 1;
    let active = true;
    let disposed = false;

    function rejectPending(message) {
      for (const item of pending.values()) {
        timers.clearTimeout(item.timer);
        item.reject(new Error(message));
      }
      pending.clear();
    }
    function reply(id, envelope) {
      if (!active || disposed || !Number.isInteger(id) || id < 1 || id > MAX_ID) return;
      const item = pending.get(id);
      if (!item || !object(envelope) || envelope.id !== id || typeof envelope.ok !== "boolean" || !boundedJSON(envelope, 524288)) return;
      if (envelope.ok && !object(envelope.result)) return;
      pending.delete(id);
      timers.clearTimeout(item.timer);
      if (envelope.ok) item.resolve(envelope.result);
      else item.reject(new Error(plain(envelope.error && envelope.error.message, 300) || "요청을 처리하지 못했습니다."));
    }
    function event(value) {
      if (!active || disposed || !object(value) || !boundedJSON(value, 524288)) return;
      for (const listener of listeners) listener(value);
    }
    scope.idolyServerReply = reply;
    scope.idolyServerEvent = event;
    return {
      request(action, payload = {}) {
        if (!validRequest(action, payload) || !boundedJSON(payload, 16384)) return Promise.reject(new Error("허용되지 않은 설정 요청입니다."));
        if (!active || disposed) return Promise.reject(new Error("설정 화면이 닫혀 있습니다."));
        const handler = scope.webkit && scope.webkit.messageHandlers && scope.webkit.messageHandlers.idolyServer;
        if (!handler || typeof handler.postMessage !== "function") return Promise.reject(new Error("앱 안에서 설정 화면을 열어 주세요."));
        if (pending.size >= MAX_PENDING || nextID > MAX_ID) return Promise.reject(new Error("진행 중인 요청을 마친 후 다시 시도해 주세요."));
        const id = nextID++;
        return new Promise((resolve, reject) => {
          const timeout = ["resources_import", "resources_export"].includes(action) ? 120000 : 20000;
          const timer = timers.setTimeout(() => {
            pending.delete(id);
            reject(new Error("응답이 지연되었습니다. 새로고침 후 상태를 확인해 주세요."));
          }, timeout);
          pending.set(id, {resolve, reject, timer});
          try { handler.postMessage({id, action, ...payload}); }
          catch (_) {
            pending.delete(id);
            timers.clearTimeout(timer);
            reject(new Error("앱에 요청을 전달하지 못했습니다."));
          }
        });
      },
      subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
      suspend() { active = false; rejectPending("설정 화면이 숨겨졌습니다."); },
      resume() { if (!disposed) active = true; },
      dispose() {
        if (disposed) return;
        disposed = true;
        active = false;
        rejectPending("설정 화면이 닫혔습니다.");
        listeners.clear();
        if (scope.idolyServerReply === reply) delete scope.idolyServerReply;
        if (scope.idolyServerEvent === event) delete scope.idolyServerEvent;
      }
    };
  }

  function formatBytes(value) {
    const bytes = typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
    if (bytes < 1024) return Math.floor(bytes) + " B";
    const exponent = Math.min(3, Math.floor(Math.log(bytes) / Math.log(1024)));
    return (bytes / Math.pow(1024, exponent)).toFixed(1) + " " + ["B", "KB", "MB", "GB"][exponent];
  }

  function createSettingsApp(scope, document, timers = scope) {
    const bridge = createBridge(scope, timers);
    const elements = new Map();
    const el = id => {
      if (!elements.has(id)) elements.set(id, document.getElementById(id));
      return elements.get(id);
    };
    const text = (id, value) => { el(id).textContent = value; };
    const forms = {
      options: {fields: ["media_mode", "download_missing_resources", "language"], valid: validOptions},
      presentation: {fields: ["custom_graphics", "quality", "target_fps", "render_scale", "max_buffer_pixel", "anti_aliasing", "shadow_resolution", "expand_photography"], valid: validPresentation},
      playback: {fields: ["wait_for_orientation"], valid: validPlayback},
      media: {fields: ["hide_video_mv", "mv_sort", "outfit_sort"], valid: validMedia}
    };
    let snapshot = null;
    let visible = document.visibilityState !== "hidden";
    let disposed = false;
    let pollTimer = null;
    let refreshing = false;
    let mutationVersion = 0;
    let visibilityVersion = 0;
    let resourcePending = false;
    let job = null;
    const logs = [];

    function message(value, error = false) {
      text("message", plain(value, 500));
      el("message").hidden = !value;
      el("message").dataset.error = String(error);
    }
    function updateForm(name, settings) {
      const form = forms[name];
      if (!form.valid(settings)) {
        el(name + "-fields").disabled = !form.value || Boolean(form.busy) || !snapshot.running || snapshot.state !== "ready";
        return;
      }
      form.value = {...settings};
      if (!form.dirty && !form.busy) {
        for (const key of form.fields) {
          const input = el(key);
          if (input.type === "checkbox") input.checked = settings[key];
          else input.value = String(settings[key]);
        }
      }
      el(name + "-fields").disabled = Boolean(form.busy) || !snapshot.running || snapshot.state !== "ready";
    }
    function settingsFromForm(name) {
      const form = forms[name];
      if (!form.value) throw new Error("설정을 먼저 불러와 주세요.");
      const value = name === "options" ? {} : {...form.value};
      for (const key of form.fields) {
        const input = el(key);
        value[key] = input.type === "checkbox" ? input.checked : typeof form.value[key] === "number" ? (input.value.trim() === "" ? NaN : Number(input.value)) : input.value;
      }
      if (!form.valid(value)) throw new Error("설정 값의 범위를 확인해 주세요.");
      return value;
    }
    function stopPolling() {
      if (pollTimer !== null) timers.clearTimeout(pollTimer);
      pollTimer = null;
    }
    function schedulePoll() {
      stopPolling();
      if (!visible || disposed) return;
      pollTimer = timers.setTimeout(() => { pollTimer = null; refresh(); }, job && ACTIVE_JOBS.has(job.state) ? 1000 : 4000);
    }
    function renderResources(runtime) {
      const library = object(runtime.resource_library) ? runtime.resource_library : {};
      job = object(library.job) ? library.job : null;
      const archivePending = object(snapshot.resource_operation) && snapshot.resource_operation.accepted === true && snapshot.resource_operation.ready === false;
      const activeJob = Boolean(job && ACTIVE_JOBS.has(job.state));
      const busy = activeJob || archivePending;
      const ready = Boolean(snapshot && snapshot.running && snapshot.state === "ready");
      for (const action of ["preview", "download", "import", "export"]) el("resources-" + action).disabled = !ready || busy || resourcePending;
      el("parallelism").disabled = busy || resourcePending || !ready;
      el("resources-cancel").disabled = !ready || !activeJob || resourcePending || !/^[A-Za-z0-9_-]{1,64}$/.test(job.job_id || "");
      const states = {preparing: "준비", running: "진행 중", export_ready: "내보내기 준비", cancelling: "취소 중", completed: "완료", partial: "일부 완료", failed: "실패", cancelled: "취소됨"};
      text("resource-state", archivePending && !activeJob ? "ZIP 준비 중" : job ? states[job.state] || "확인 중" : "대기");
      el("resource-progress").hidden = !job;
      if (job) {
        const total = count(job.total_files);
        const checked = count(job.verified_files);
        el("resource-progress").max = Math.max(1, total);
        el("resource-progress").value = Math.min(checked, total);
        const action = {download: "받기", import: "가져오기", export: "내보내기"}[job.action] || "작업";
        text("resource-summary", action + " · 검증 " + checked + "/" + total + "개 · " + formatBytes(job.verified_bytes) + " / " + formatBytes(job.total_bytes) + "\n수신 " + formatBytes(job.received_bytes) + " · 재사용 " + count(job.cache_hit_files) + "개 · 가져옴 " + count(job.imported_files) + "개\n실패 " + count(job.failed_files) + "개 · 미보관 " + count(job.missing_files) + "개");
        const phases = object(job.phase_active_files) ? job.phase_active_files : {};
        const phaseText = [["connecting", "연결"], ["receiving", "받기"], ["checking", "검증"], ["saving", "저장"], ["copying", "복사"]].map(([key, title]) => title + " " + count(phases[key])).join(" · ");
        const parallel = choice(job.parallelism, [1, 2, 4, 8]) ? "동시 " + job.parallelism + "개 · " : "";
        const elapsed = typeof job.elapsed_seconds === "number" && Number.isFinite(job.elapsed_seconds) && job.elapsed_seconds >= 0 ? Math.floor(job.elapsed_seconds) : 0;
        text("resource-detail", parallel + "평균 " + formatBytes(job.average_bytes_per_second) + "/s · " + elapsed + "초\n" + phaseText + (job.error_code ? "\n오류: " + plain(job.error_code, 80) : ""));
      } else {
        const catalog = object(library.catalogs) && object(library.catalogs.ios) ? library.catalogs.ios : null;
        text("resource-summary", archivePending ? "ZIP 작업을 준비하고 있습니다." : catalog ? "포함 목록 " + count(catalog.object_count) + "개 · " + formatBytes(catalog.total_bytes) : ready ? "목록·용량 확인을 누르면 전체 예상 용량을 표시합니다." : "서버가 준비되면 리소스를 관리할 수 있습니다.");
        text("resource-detail", "");
      }
    }
    function renderDiagnostics(runtime) {
      const diagnostic = object(runtime.client_diagnostics) ? runtime.client_diagnostics : {};
      text("diagnostic-summary", plain(diagnostic.summary, 500) || "게임 진단 대기 중");
      const details = {
        server: {state: snapshot.state, running: snapshot.running, restart_required: snapshot.restart_required},
        game: diagnostic,
        presentation: object(runtime.presentation) ? runtime.presentation.client || null : null,
        playback: object(runtime.playback) ? runtime.playback.client || null : null,
        resource_transfer: runtime.resource_transfer || null,
        asset_transfer: runtime.asset_transfer || null,
        resource_operation: object(snapshot.resource_operation) ? {
          accepted: snapshot.resource_operation.accepted,
          ready: snapshot.resource_operation.ready,
          error: snapshot.resource_operation.error || null
        } : null
      };
      // Never interpolate server strings as markup, URLs or executable code.
      let detail = JSON.stringify(details, null, 2).slice(0, 24000);
      const recent = (Array.isArray(runtime.logs) ? runtime.logs.filter(line => typeof line === "string").slice(-40).map(line => plain(line, 1000)) : []).concat(logs).slice(-50);
      if (recent.length) detail += "\n\n최근 기록\n" + recent.join("\n");
      text("diagnostics", detail);
    }
    function renderStatus(value) {
      if (!object(value) || !object(value.options)) return false;
      const runtime = object(value.runtime) ? value.runtime : {};
      snapshot = {...value, runtime};
      const titles = {idle: "대기", starting: "준비 중", ready: "실행 중", failed: "시작 실패", closed: "종료됨"};
      text("server-state", titles[value.state] || "확인 중");
      text("server-summary", value.state === "ready" && value.running ? "로컬 서버가 게임 연결을 기다리고 있습니다." : value.last_error ? plain(value.last_error, 300) : value.state === "starting" ? "서버와 데이터를 준비하고 있습니다." : "로컬 서버가 실행 중이 아닙니다.");
      el("restart-notice").hidden = value.restart_required !== true;
      updateForm("options", value.options);
      updateForm("presentation", object(runtime.presentation) ? runtime.presentation.settings : null);
      updateForm("playback", object(runtime.playback) ? runtime.playback.settings : null);
      updateForm("media", object(runtime.media_options) ? runtime.media_options.settings : null);
      const effective = value.effective_options;
      text("effective-options", validOptions(effective) ? "현재: " + (effective.media_mode ? "감상 모드" : "일반 모드") + " · " + LANGUAGES[effective.language] + " · 자동 받기 " + (effective.download_missing_resources ? "켜짐" : "꺼짐") : "현재 적용 값은 서버 준비 후 표시됩니다.");
      const graphics = object(runtime.presentation) && object(runtime.presentation.client) ? runtime.presentation.client : {};
      const graphicsLabels = {waiting: "적용 대기", applied: "게임 적용 확인", disabled: "원본 설정", unsupported: "미지원", waiting_for_scene: "장면 대기", init_failed: "초기화 실패"};
      text("graphics-state", graphicsLabels[graphics.status] || "대기");
      text("graphics-detail", graphics.status === "applied" ? "게임에서 현재 그래픽 설정을 확인했습니다. 화면 확장은 촬영 장면에서 확인해 주세요." : graphics.status === "waiting_for_scene" ? "설정이 저장되었습니다. 촬영·360 장면에서 적용 상태를 확인합니다." : "저장 확인과 게임 적용 확인은 다릅니다. 해당 장면에 들어가 적용 상태를 확인해 주세요.");
      const playback = object(runtime.playback) && object(runtime.playback.client) ? runtime.playback.client : {};
      text("playback-state", playback.applied === true ? "게임 적용 확인" : playback.supported === false ? "미지원" : "적용 대기");
      const media = object(runtime.media_options) ? runtime.media_options : {};
      const mediaChanged = validMedia(media.settings) && validMedia(media.effective_settings) && forms.media.fields.some(key => media.settings[key] !== media.effective_settings[key]);
      text("media-effective", mediaChanged ? "변경한 목록 설정은 다음 앱 실행부터 적용됩니다." : "목록 설정은 다음 앱 실행부터 적용됩니다.");
      renderResources(runtime);
      renderDiagnostics(runtime);
      return true;
    }
    async function refresh() {
      if (!visible || disposed || refreshing) return;
      refreshing = true;
      const version = mutationVersion;
      el("refresh").disabled = true;
      try {
        const result = await bridge.request("status");
        if (visible && !disposed && version === mutationVersion && !renderStatus(result)) message("서버 상태 형식을 확인하지 못했습니다.", true);
      } catch (error) {
        if (visible && !disposed && version === mutationVersion) message(error.message, true);
      } finally {
        refreshing = false;
        if (!disposed) el("refresh").disabled = false;
        schedulePoll();
      }
    }
    async function save(name) {
      const form = forms[name];
      if (!visible || disposed || form.busy || !snapshot || !snapshot.running || snapshot.state !== "ready") return;
      let value;
      try { value = settingsFromForm(name); }
      catch (error) { message(error.message, true); return; }
      form.busy = true;
      mutationVersion++;
      const visibility = visibilityVersion;
      el(name + "-fields").disabled = true;
      try {
        const result = await bridge.request("save_" + name, name === "options" ? value : {settings: value});
        if (!visible || disposed || visibility !== visibilityVersion) return;
        form.dirty = false;
        form.busy = false;
        if (!renderStatus(result)) { await refresh(); return; }
        message(name === "options" || name === "media" ? "저장했습니다. 다음 앱 실행부터 적용됩니다." : "설정을 저장했습니다. 게임 적용 상태를 확인해 주세요.");
      } catch (error) {
        if (visible && !disposed && visibility === visibilityVersion) message(error.message, true);
      } finally {
        form.busy = false;
        if (!disposed) el(name + "-fields").disabled = !form.value || !snapshot || !snapshot.running || snapshot.state !== "ready";
        schedulePoll();
      }
    }
    async function resource(action) {
      if (!visible || disposed || resourcePending || !snapshot || !snapshot.running || snapshot.state !== "ready") return;
      const payload = action === "cancel" ? {job_id: job && job.job_id} : action === "download" ? {parallelism: Number(el("parallelism").value)} : {};
      resourcePending = true;
      mutationVersion++;
      const visibility = visibilityVersion;
      if (snapshot) renderResources(snapshot.runtime);
      try {
        const result = await bridge.request("resources_" + action, payload);
        if (!visible || disposed || visibility !== visibilityVersion) return;
        message(result.cancelled === true ? "파일 선택을 취소했습니다." : {preview: "리소스 목록을 확인했습니다.", download: "리소스 받기를 시작했습니다.", cancel: "작업 취소를 요청했습니다.", import: "ZIP 가져오기를 시작했습니다. 진행 상태를 확인해 주세요.", export: result.ready === true ? "ZIP을 준비했습니다. 파일 앱에서 저장해 주세요." : "ZIP을 준비하고 있습니다. 완료되면 파일 앱에서 저장할 수 있습니다."}[action]);
      } catch (error) {
        if (visible && !disposed && visibility === visibilityVersion) message(error.message, true);
      } finally {
        resourcePending = false;
        if (!disposed && snapshot) renderResources(snapshot.runtime);
        if (visible && !disposed) refresh();
      }
    }
    function onVisibility() {
      visible = document.visibilityState !== "hidden";
      mutationVersion++;
      visibilityVersion++;
      stopPolling();
      if (visible) { bridge.resume(); Promise.resolve().then(refresh); }
      else bridge.suspend();
    }
    function dispose() {
      if (disposed) return;
      disposed = true;
      visible = false;
      stopPolling();
      bridge.dispose();
      document.removeEventListener("visibilitychange", onVisibility);
      scope.removeEventListener("pagehide", dispose);
    }
    for (const [name, form] of Object.entries(forms)) {
      form.dirty = false;
      form.busy = false;
      el(name + "-form").addEventListener("input", () => { form.dirty = true; });
      el(name + "-form").addEventListener("change", () => { form.dirty = true; });
      el(name + "-form").addEventListener("submit", event => { event.preventDefault(); save(name); });
    }
    el("refresh").addEventListener("click", () => { message(""); refresh(); });
    for (const action of ["preview", "download", "import", "export", "cancel"]) el("resources-" + action).addEventListener("click", () => resource(action));
    bridge.subscribe(event => {
      if (object(event.status) && ["ready", "status", "error", "closed"].includes(event.event)) renderStatus(event.status);
      if (event.event === "log" && typeof event.message === "string") {
        logs.push(plain(event.message, 1000));
        if (logs.length > 40) logs.shift();
        if (snapshot) renderDiagnostics(snapshot.runtime);
      }
      if (["resource_result", "resource_error"].includes(event.event)) {
        if (event.accepted === false || event.event === "resource_error") message("ZIP 작업을 마치지 못했습니다. 확인된 파일과 기존 보관 자료는 유지됩니다.", true);
        else if (event.ready === true) message(event.output_path ? "ZIP을 준비했습니다. 파일 앱에서 저장해 주세요." : "ZIP 가져오기를 마쳤습니다.");
        else if (event.message) message(event.message);
        refresh();
      }
      if (pollTimer === null) schedulePoll();
    });
    document.addEventListener("visibilitychange", onVisibility);
    scope.addEventListener("pagehide", dispose);
    if (visible) refresh();
    else bridge.suspend();
    return {dispose};
  }

  if (typeof module !== "undefined" && module.exports) module.exports = {createBridge, createSettingsApp, formatBytes};
  else if (root.document) createSettingsApp(root, root.document);
})(typeof window !== "undefined" ? window : globalThis);
