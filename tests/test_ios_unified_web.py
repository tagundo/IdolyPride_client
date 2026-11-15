"""Behavioral tests for the local settings page; no browser packages or network."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


WEB = Path(__file__).resolve().parents[1] / "ios-unified" / "web"
NODE = shutil.which("node")


HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const api = require(WEB + '/app.js');
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
class Target {
  constructor() { this.listeners = new Map(); }
  addEventListener(name, fn) { if (!this.listeners.has(name)) this.listeners.set(name, new Set()); this.listeners.get(name).add(fn); }
  removeEventListener(name, fn) { if (this.listeners.has(name)) this.listeners.get(name).delete(fn); }
  fire(name) { for (const fn of this.listeners.get(name) || []) fn({preventDefault() {}}); }
}
class Element extends Target {
  constructor(tag) {
    super(); this.textContent = ''; this.value = ''; this.checked = /\bchecked\b/.test(tag);
    this.disabled = /\bdisabled\b/.test(tag); this.hidden = /\bhidden\b/.test(tag); this.dataset = {};
    this.type = (tag.match(/\btype="([^"]+)"/) || [,''])[1];
  }
  set innerHTML(_) { throw new Error('Untrusted data reached an HTML sink'); }
}
function environment(hidden = false) {
  const scope = new Target();
  const document = new Target();
  document.visibilityState = hidden ? 'hidden' : 'visible';
  const elements = new Map();
  for (const match of fs.readFileSync(WEB + '/index.html', 'utf8').matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)) elements.set(match[1], new Element(match[0]));
  elements.get('parallelism').value = '4';
  document.getElementById = id => { assert.ok(elements.has(id), 'Real HTML element exists: ' + id); return elements.get(id); };
  const posted = [];
  scope.webkit = {messageHandlers: {idolyServer: {postMessage(value) { posted.push(JSON.parse(JSON.stringify(value))); }}}};
  let now = 0, sequence = 0;
  const tasks = new Map();
  const timers = {
    setTimeout(fn, delay) { const id = ++sequence; tasks.set(id, {fn, at: now + delay}); return id; },
    clearTimeout(id) { tasks.delete(id); }
  };
  async function tick(ms) {
    now += ms;
    for (let i = 0; i < 100; i++) {
      const next = [...tasks].find(([, task]) => task.at <= now);
      if (!next) return;
      tasks.delete(next[0]); next[1].fn(); await flush();
    }
    throw new Error('Unbounded timer loop');
  }
  function respond(request, result) { scope.idolyServerReply(request.id, {id: request.id, ok: true, result}); }
  async function visibility(hidden) { document.visibilityState = hidden ? 'hidden' : 'visible'; document.fire('visibilitychange'); await flush(); }
  return {scope, document, elements, posted, tasks, timers, tick, respond, visibility};
}
function status() {
  return {
    state: 'ready', running: true, restart_required: false,
    options: {schema: 1, media_mode: true, download_missing_resources: true, language: 'ko'},
    effective_options: {schema: 1, media_mode: true, download_missing_resources: true, language: 'ko'},
    runtime: {
      presentation: {settings: {schema: 1, revision: 1700000000001, custom_graphics: false, quality: 0, target_fps: 0, render_scale: 1.234, max_buffer_pixel: 2222, anti_aliasing: -1, shadow_resolution: 0, expand_photography: false}, client: {status: 'waiting'}},
      playback: {settings: {schema: 1, revision: 1700000000002, wait_for_orientation: true}, client: {supported: true, applied: false}},
      media_options: {settings: {schema: 1, revision: 1700000000003, hide_video_mv: false, mv_sort: 'recent', outfit_sort: 'original'}},
      resource_library: {catalogs: {ios: {object_count: 5, total_bytes: 10240}}, job: null},
      client_diagnostics: {summary: '게임 진단 대기 중'}, logs: []
    }
  };
}
"""


def run_js(body: str) -> None:
    if NODE is None:
        pytest.skip("Node.js is required for the bundled JavaScript behavior checks")
    program = "const WEB = " + json.dumps(str(WEB)) + ";\n" + HARNESS
    program += "\nlet bodyCompleted = false;\nprocess.on('beforeExit', () => { if (!bodyCompleted) { console.error('Async test body did not complete'); process.exitCode = 1; } });\n"
    program += "(async () => {\n" + body + "\n})().then(() => { bodyCompleted = true; }, error => { bodyCompleted = true; console.error(error); process.exitCode = 1; });\n"
    subprocess.run([NODE, "--unhandled-rejections=strict", "-e", program], check=True, timeout=15, capture_output=True, text=True)


def test_bridge_rejects_paths_unknown_actions_and_invalid_downloads() -> None:
    run_js(r"""
const env = environment();
const bridge = api.createBridge(env.scope, env.timers);
for (const [action, payload] of [
  ['run', {}], ['status', {path: '/private/file'}],
  ['resources_import', {path: '/private/file.zip'}],
  ['resources_export', {path: '/private/file.zip'}],
  ['resources_download', {platform: 'android', parallelism: 4}],
  ['resources_download', {parallelism: 9}],
  ['resources_download', {parallelism: '4'}],
  ['resources_cancel', {job_id: '../other'}],
  ['save_interface_language', {}],
  ['save_interface_language', {interface_language: 'fr'}],
  ['save_interface_language', {interface_language: true}],
  ['save_interface_language', {interface_language: 'en', language: 'ja'}],
  ['save_interface_language', {interface_language: 'en', media_mode: false}],
  ['save_playback', {settings: {schema: 1, revision: 0, wait_for_orientation: 'false'}}]
]) await assert.rejects(bridge.request(action, payload));
assert.equal(env.posted.length, 0);
const importRequest = bridge.request('resources_import');
assert.deepEqual(env.posted[0], {id: 1, action: 'resources_import'});
env.respond(env.posted[0], {cancelled: true});
await importRequest;
bridge.dispose();
assert.equal(env.tasks.size, 0);
""")


def test_bridge_ignores_mismatched_stale_and_repeated_replies() -> None:
    run_js(r"""
const env = environment();
const bridge = api.createBridge(env.scope, env.timers);
let received = false;
const first = bridge.request('status').then(result => { received = result.marker; });
const request = env.posted[0];
env.scope.idolyServerReply(request.id, {id: request.id + 1, ok: true, result: {marker: 'wrong'}});
env.scope.idolyServerReply('1', {id: request.id, ok: true, result: {marker: 'wrong'}});
await flush();
assert.equal(received, false);
env.respond(request, {marker: 'first'});
await first;
assert.equal(received, 'first');
const second = bridge.request('status');
const secondID = env.posted[1].id;
env.respond(request, {marker: 'replayed'});
env.scope.idolyServerReply(secondID, {id: secondID, ok: false, error: {message: '실패 확인'}});
await assert.rejects(second, /실패 확인/);
const abandoned = bridge.request('status');
const rejectAbandoned = assert.rejects(abandoned, /숨겨/);
bridge.suspend();
await rejectAbandoned;
assert.equal(env.tasks.size, 0);
bridge.resume();
const fresh = bridge.request('status');
assert.ok(env.posted.at(-1).id > secondID);
env.respond(env.posted[2], {marker: 'hidden old reply'});
env.respond(env.posted.at(-1), {marker: 'fresh'});
assert.deepEqual(await fresh, {marker: 'fresh'});
bridge.dispose();
""")


def test_bridge_bounds_pending_requests_and_times_out_without_accepting_late_reply() -> None:
    run_js(r"""
const env = environment();
const bridge = api.createBridge(env.scope, env.timers);
const requests = Array.from({length: 16}, () => bridge.request('status').catch(error => error.message));
await assert.rejects(bridge.request('status'), /진행 중/);
assert.equal(env.posted.length, 16);
await env.tick(20000);
assert.ok((await Promise.all(requests)).every(value => value.includes('지연')));
assert.equal(env.tasks.size, 0);
const fresh = bridge.request('status');
env.respond(env.posted[0], {marker: 'late'});
env.respond(env.posted.at(-1), {marker: 'current'});
assert.equal((await fresh).marker, 'current');
bridge.dispose();
""")


def test_ui_stops_all_work_when_hidden_and_releases_callbacks_on_close() -> None:
    run_js(r"""
const env = environment(true);
const app = api.createSettingsApp(env.scope, env.document, env.timers);
await env.tick(60000);
assert.equal(env.posted.length, 0);
assert.equal(env.tasks.size, 0);
await env.visibility(false);
assert.equal(env.posted.length, 1);
env.respond(env.posted[0], status());
await flush();
assert.equal(env.elements.get('wait_for_orientation').checked, true);
assert.equal(env.elements.get('playback-fields').disabled, false);
await env.tick(4000);
assert.equal(env.posted.length, 2);
await env.visibility(true);
assert.equal(env.tasks.size, 0);
const count = env.posted.length;
env.respond(env.posted.at(-1), {...status(), state: 'failed'});
await env.tick(60000);
assert.equal(env.posted.length, count);
assert.equal(env.elements.get('server-state').textContent, '실행 중');
await env.visibility(false);
assert.equal(env.posted.length, count + 1);
env.respond(env.posted.at(-1), status());
await flush();
env.scope.fire('pagehide');
assert.equal(env.tasks.size, 0);
assert.equal(env.scope.idolyServerReply, undefined);
assert.equal(env.scope.idolyServerEvent, undefined);
await env.visibility(false);
await env.tick(60000);
assert.equal(env.posted.length, count + 1);
app.dispose();
""")


def test_ui_preserves_saved_values_dirty_edits_and_ignores_pre_save_status_reply() -> None:
    run_js(r"""
const env = environment();
const app = api.createSettingsApp(env.scope, env.document, env.timers);
const current = status();
env.respond(env.posted[0], current);
await flush();
assert.equal(env.elements.get('render_scale').value, '1.234');
assert.equal(env.elements.get('max_buffer_pixel').value, '2222');
env.elements.get('quality').value = '40';
env.elements.get('presentation-form').fire('change');
await env.tick(4000);
env.respond(env.posted.at(-1), current);
await flush();
assert.equal(env.elements.get('quality').value, '40', 'Polling keeps unsaved edits');
await env.tick(4000);
const oldStatus = env.posted.at(-1);
env.elements.get('presentation-form').fire('submit');
const save = env.posted.at(-1);
assert.equal(save.action, 'save_presentation');
assert.deepEqual(save.settings, {...current.runtime.presentation.settings, quality: 40});
const saved = status();
saved.runtime.presentation.settings = {...save.settings, revision: save.settings.revision + 1};
env.respond(save, saved);
await flush();
env.respond(oldStatus, current);
await flush();
assert.equal(env.elements.get('quality').value, '40');
env.elements.get('wait_for_orientation').checked = false;
env.elements.get('playback-form').fire('change');
env.elements.get('playback-form').fire('submit');
const playback = env.posted.at(-1);
assert.deepEqual(playback.settings, {...current.runtime.playback.settings, wait_for_orientation: false});
const savedPlayback = status();
savedPlayback.runtime.playback.settings = {...playback.settings, revision: playback.settings.revision + 1};
env.respond(playback, savedPlayback);
await flush();
assert.equal(env.elements.get('wait_for_orientation').checked, false);
app.dispose();
""")


def test_ui_options_and_media_keep_boot_values_until_next_launch() -> None:
    run_js(r"""
const env = environment();
const app = api.createSettingsApp(env.scope, env.document, env.timers);
const initial = status();
env.respond(env.posted[0], initial);
await flush();
env.elements.get('media_mode').checked = false;
env.elements.get('download_missing_resources').checked = false;
env.elements.get('language').value = 'en';
env.elements.get('options-form').fire('change');
env.elements.get('options-form').fire('submit');
const options = env.posted.at(-1);
assert.deepEqual(options, {id: options.id, action: 'save_options', media_mode: false, download_missing_resources: false, language: 'en', interface_language: 'system'});
const saved = status();
saved.options = {schema: 1, media_mode: false, download_missing_resources: false, language: 'en'};
saved.restart_required = true;
env.respond(options, saved);
await flush();
assert.equal(env.elements.get('restart-notice').hidden, false);
assert.match(env.elements.get('effective-options').textContent, /한국어/);
assert.equal(env.elements.get('language').value, 'en');
env.elements.get('hide_video_mv').checked = true;
env.elements.get('mv_sort').value = 'old';
env.elements.get('outfit_sort').value = 'title';
env.elements.get('media-form').fire('change');
env.elements.get('media-form').fire('submit');
const media = env.posted.at(-1);
assert.deepEqual(media.settings, {...initial.runtime.media_options.settings, hide_video_mv: true, mv_sort: 'old', outfit_sort: 'title'});
env.respond(media, saved);
await flush();
app.dispose();
""")


def test_ui_native_files_actions_progress_and_cancel_use_fixed_host_payloads() -> None:
    run_js(r"""
const env = environment();
const app = api.createSettingsApp(env.scope, env.document, env.timers);
env.respond(env.posted[0], status());
await flush();
for (const action of ['import', 'export']) {
  env.elements.get('resources-' + action).fire('click');
  const request = env.posted.at(-1);
  assert.deepEqual(request, {id: request.id, action: 'resources_' + action});
  env.respond(request, {cancelled: true});
  await flush();
  env.respond(env.posted.at(-1), status());
  await flush();
}
env.elements.get('parallelism').value = '8';
env.elements.get('resources-download').fire('click');
const download = env.posted.at(-1);
assert.deepEqual(download, {id: download.id, action: 'resources_download', parallelism: 8});
env.respond(download, {job_id: 'safe-job'});
await flush();
const active = status();
active.runtime.resource_library.job = {job_id: 'safe-job', action: 'download', state: 'running', total_files: 10, verified_files: 3, total_bytes: 10000, verified_bytes: 3000, received_bytes: 2000, parallelism: 8, phase_active_files: {receiving: 2, checking: 1}};
env.respond(env.posted.at(-1), active);
await flush();
assert.equal(env.elements.get('resource-progress').value, 3);
assert.equal(env.elements.get('resource-progress').max, 10);
assert.equal(env.elements.get('resources-download').disabled, true);
assert.equal(env.elements.get('resources-import').disabled, true);
assert.equal(env.elements.get('resources-cancel').disabled, false);
assert.match(env.elements.get('resource-detail').textContent, /동시 8개/);
env.elements.get('resources-cancel').fire('click');
const cancel = env.posted.at(-1);
assert.deepEqual(cancel, {id: cancel.id, action: 'resources_cancel', job_id: 'safe-job'});
env.respond(cancel, {state: 'cancelling'});
await flush();
app.dispose();
""")


def test_ui_archive_stays_busy_until_completion_and_reports_late_failure() -> None:
    run_js(r"""
const env = environment();
const app = api.createSettingsApp(env.scope, env.document, env.timers);
env.respond(env.posted[0], status());
await flush();
env.elements.get('resources-export').fire('click');
env.respond(env.posted.at(-1), {accepted: true, ready: false, output_path: '/private/exports/approved.zip', job: null});
await flush();
assert.match(env.elements.get('message').textContent, /준비하고/);
const preparing = status();
preparing.resource_operation = {accepted: true, ready: false, job: null};
env.respond(env.posted.at(-1), preparing);
await flush();
assert.equal(env.elements.get('resources-import').disabled, true);
assert.equal(env.elements.get('resources-download').disabled, true);
assert.equal(env.elements.get('resources-cancel').disabled, true);
env.scope.idolyServerEvent({event: 'resource_result', accepted: false, ready: false, error: {code: 'archive_failed'}});
assert.equal(env.elements.get('message').dataset.error, 'true');
assert.match(env.elements.get('message').textContent, /마치지 못/);
env.respond(env.posted.at(-1), status());
await flush();
assert.equal(env.elements.get('resources-export').disabled, false);
assert.ok(!env.elements.get('message').textContent.includes('/private'));
app.dispose();
""")


def test_ui_treats_server_strings_as_text_and_renders_startup_without_runtime() -> None:
    run_js(r"""
const env = environment();
const app = api.createSettingsApp(env.scope, env.document, env.timers);
const malicious = '<img src=x onerror="globalThis.compromised=true">';
env.respond(env.posted[0], {state: 'failed', running: false, options: status().options, runtime: null, last_error: malicious});
await flush();
assert.equal(env.elements.get('server-summary').textContent, malicious);
assert.equal(env.elements.get('options-fields').disabled, true);
assert.equal(env.elements.get('presentation-fields').disabled, true);
const ready = status();
ready.runtime.logs = [malicious];
ready.runtime.client_diagnostics.summary = malicious;
env.scope.idolyServerEvent({event: 'ready', status: ready});
assert.equal(env.elements.get('diagnostic-summary').textContent, malicious);
assert.ok(env.elements.get('diagnostics').textContent.includes(malicious));
env.scope.idolyServerEvent({event: 'log', message: malicious});
assert.equal(globalThis.compromised, undefined);
assert.equal(env.posted.length, 1);
env.scope.idolyServerEvent({event: 'error', status: {state: 'failed', running: false, options: ready.options, runtime: {running: false}}});
assert.equal(env.elements.get('presentation-fields').disabled, true);
assert.equal(env.elements.get('playback-fields').disabled, true);
app.dispose();
""")


def test_page_has_only_bundled_scripts_and_no_network_or_html_sinks() -> None:
    html = (WEB / "index.html").read_text()
    javascript = (WEB / "app.js").read_text()
    assert 'connect-src \'none\'' in html
    assert 'script-src \'self\'' in html
    assert 'src="app.js"' in html
    assert 'href="styles.css"' in html
    assert not any(value in javascript for value in ("innerHTML", "insertAdjacentHTML", "eval(", "fetch(", "XMLHttpRequest", "setInterval("))
    assert not any(value in html for value in ("https://", "http://", "<img", "onclick="))


def test_graphics_presets_keep_custom_values_and_save_upper_supported_choices() -> None:
    run_js(r"""
const env = environment();
const app = api.createSettingsApp(env.scope, env.document, env.timers);
env.respond(env.posted[0], status());
await flush();
assert.equal(env.elements.get('render_scale').value, '1.234');
assert.equal(env.elements.get('render_scale_preset').value, 'custom');
assert.equal(env.elements.get('max_buffer_pixel').value, '2222');
assert.equal(env.elements.get('max_buffer_pixel_preset').value, 'custom');
env.elements.get('render_scale_preset').value = '2';
env.elements.get('render_scale_preset').fire('change');
env.elements.get('max_buffer_pixel_preset').value = '4096';
env.elements.get('max_buffer_pixel_preset').fire('change');
assert.equal(env.elements.get('render_scale').value, '2');
assert.equal(env.elements.get('max_buffer_pixel').value, '4096');
env.elements.get('presentation-form').fire('submit');
const request = env.posted.at(-1);
assert.equal(request.action, 'save_presentation');
assert.equal(request.settings.render_scale, 2);
assert.equal(request.settings.max_buffer_pixel, 4096);
env.respond(request, status());
await flush();
env.elements.get('render_scale').value = '1.875';
env.elements.get('render_scale').fire('input');
assert.equal(env.elements.get('render_scale_preset').value, 'custom');
env.elements.get('presentation-form').fire('submit');
assert.equal(env.posted.at(-1).settings.render_scale, 1.875);
app.dispose();
""")


def test_interface_language_is_available_before_ready_without_overwriting_game_options() -> None:
    run_js(r"""
const env = environment();
env.scope.navigator = {language: 'en-US'};
const app = api.createSettingsApp(env.scope, env.document, env.timers);
assert.equal(env.elements.get('interface_language').disabled, false);
assert.equal(env.elements.get('interface_language').value, 'system');
const initialStatus = env.posted[0];
env.elements.get('interface_language').value = 'ja';
env.elements.get('interface_language').fire('change');
const interfaceRequest = env.posted.at(-1);
assert.deepEqual(interfaceRequest, {id: interfaceRequest.id, action: 'save_interface_language', interface_language: 'ja'});
assert.equal(env.posted.filter(request => request.action === 'save_options').length, 0);
assert.equal(env.elements.get('interface_language').disabled, false);
env.respond(interfaceRequest, {interface_language: 'ja'});
await flush();
env.respond(initialStatus, status());
await flush();
assert.equal(env.elements.get('interface_language').value, 'ja');
assert.equal(env.elements.get('language').value, 'ko');
assert.equal(env.elements.get('media_mode').checked, true);
assert.equal(env.elements.get('download_missing_resources').checked, true);
env.elements.get('options-form').fire('submit');
const request = env.posted.at(-1);
assert.deepEqual(request, {id: request.id, action: 'save_options', media_mode: true,
  download_missing_resources: true, language: 'ko', interface_language: 'ja'});
const saved = status(); saved.options.interface_language = 'ja';
env.respond(request, saved);
await flush();
assert.equal(env.elements.get('interface_language').value, 'ja');
assert.equal(env.elements.get('server-state').textContent, api.translateUI('실행 중', 'ja'));
app.dispose();
""")


def test_saved_interface_language_overrides_device_and_preserves_unsaved_graphics() -> None:
    run_js(r"""
const env = environment(); env.scope.navigator = {languages: ['ja-JP'], language: 'ja-JP'};
const app = api.createSettingsApp(env.scope, env.document, env.timers);
const ready = status(); ready.options.interface_language = 'en';
env.respond(env.posted[0], ready); await flush();
assert.equal(env.elements.get('interface_language').value, 'en');
assert.equal(env.elements.get('server-state').textContent, api.translateUI('실행 중', 'en'));
env.elements.get('render_scale').value = '1.875';
env.elements.get('render_scale').fire('input');
env.elements.get('media_mode').checked = false;
env.elements.get('download_missing_resources').checked = false;
env.elements.get('language').value = 'ja';
env.elements.get('options-form').fire('change');
env.elements.get('interface_language').value = 'ko';
env.elements.get('interface_language').fire('change');
const interfaceRequest = env.posted.at(-1);
assert.deepEqual(interfaceRequest, {id: interfaceRequest.id, action: 'save_interface_language', interface_language: 'ko'});
assert.equal(env.elements.get('render_scale').value, '1.875');
assert.equal(env.elements.get('server-state').textContent, '실행 중');
assert.equal(env.elements.get('language').value, 'ja');
assert.equal(env.posted.filter(request => request.action === 'save_options').length, 0);
env.respond(interfaceRequest, {interface_language: 'ko'}); await flush();
await env.tick(4000);
const poll = env.posted.at(-1); assert.equal(poll.action, 'status');
env.respond(poll, ready); await flush();
assert.equal(env.elements.get('interface_language').value, 'ko');
assert.equal(env.elements.get('media_mode').checked, false);
assert.equal(env.elements.get('download_missing_resources').checked, false);
assert.equal(env.elements.get('language').value, 'ja');
assert.equal(env.elements.get('render_scale').value, '1.875');
env.elements.get('options-form').fire('submit');
const options = env.posted.at(-1);
assert.deepEqual(options, {id: options.id, action: 'save_options', media_mode: false,
  download_missing_resources: false, language: 'ja', interface_language: 'ko'});
const saved = status(); saved.options = {...options, schema: 1};
delete saved.options.id; delete saved.options.action;
env.respond(options, saved); await flush();
assert.equal(env.elements.get('render_scale').value, '1.875');
env.elements.get('presentation-form').fire('submit');
const graphics = env.posted.at(-1);
assert.equal(graphics.action, 'save_presentation');
assert.equal(graphics.settings.render_scale, 1.875);
env.respond(graphics, saved); await flush();
app.dispose();
assert.equal(api.resolveInterfaceLanguage('system', {languages: ['en-GB']}), 'en');
assert.equal(api.resolveInterfaceLanguage('system', {language: 'ja_JP'}), 'ja');
assert.equal(api.resolveInterfaceLanguage('system', {language: 'fr-FR'}), 'en');
assert.equal(api.resolveInterfaceLanguage('ko', {language: 'en-US'}), 'ko');
assert.equal(api.translateUI('<img src=x onerror=malicious>', 'ja'), '<img src=x onerror=malicious>');
""")


def test_interface_language_keeps_latest_choice_when_acknowledgements_and_status_arrive_out_of_order() -> None:
    run_js(r"""
const env = environment();
const app = api.createSettingsApp(env.scope, env.document, env.timers);
const initial = status(); initial.options.interface_language = 'ko';
env.respond(env.posted[0], initial); await flush();
await env.tick(4000);
const oldPoll = env.posted.at(-1); assert.equal(oldPoll.action, 'status');
env.elements.get('interface_language').value = 'ja';
env.elements.get('interface_language').fire('change');
const japanese = env.posted.at(-1);
env.elements.get('interface_language').value = 'en';
env.elements.get('interface_language').fire('change');
const english = env.posted.at(-1);
assert.deepEqual(japanese, {id: japanese.id, action: 'save_interface_language', interface_language: 'ja'});
assert.deepEqual(english, {id: english.id, action: 'save_interface_language', interface_language: 'en'});
assert.notEqual(japanese.id, english.id);
assert.equal(env.elements.get('server-state').textContent, api.translateUI('실행 중', 'en'));
env.respond(english, {options: {...initial.options, interface_language: 'en'}}); await flush();
env.respond(japanese, {interface_language: 'ja'}); await flush();
env.respond(oldPoll, initial); await flush();
env.scope.idolyServerEvent({event: 'status', status: initial});
assert.equal(env.elements.get('interface_language').value, 'en');
assert.equal(env.elements.get('server-state').textContent, api.translateUI('실행 중', 'en'));
assert.equal(env.posted.filter(request => request.action === 'save_options').length, 0);
app.dispose();
""")


def test_interface_language_survives_an_older_game_options_save_reply() -> None:
    run_js(r"""
const env = environment();
const app = api.createSettingsApp(env.scope, env.document, env.timers);
const initial = status(); initial.options.interface_language = 'ko';
env.respond(env.posted[0], initial); await flush();
env.elements.get('language').value = 'ja';
env.elements.get('options-form').fire('change');
env.elements.get('options-form').fire('submit');
const options = env.posted.at(-1); assert.equal(options.action, 'save_options');
assert.equal(options.interface_language, 'ko');
env.elements.get('interface_language').value = 'en';
env.elements.get('interface_language').fire('change');
const interfaceRequest = env.posted.at(-1);
assert.equal(interfaceRequest.action, 'save_interface_language');
env.respond(interfaceRequest, {interface_language: 'en'}); await flush();
const saved = status(); saved.options = {...initial.options, language: 'ja'};
env.respond(options, saved); await flush();
assert.equal(env.elements.get('interface_language').value, 'en');
assert.equal(env.elements.get('server-state').textContent, api.translateUI('실행 중', 'en'));
assert.equal(env.elements.get('language').value, 'ja');
env.elements.get('media_mode').checked = false;
env.elements.get('options-form').fire('change');
env.elements.get('options-form').fire('submit');
const subsequent = env.posted.at(-1);
assert.equal(subsequent.interface_language, 'en');
assert.equal(subsequent.language, 'ja');
assert.equal(subsequent.media_mode, false);
app.dispose();
""")


def test_interface_language_failures_and_timeouts_do_not_revert_choice_or_dirty_game_options() -> None:
    run_js(r"""
const env = environment();
const app = api.createSettingsApp(env.scope, env.document, env.timers);
const initial = status(); initial.options.interface_language = 'en';
env.respond(env.posted[0], initial); await flush();
env.elements.get('language').value = 'ja';
env.elements.get('options-form').fire('change');
env.elements.get('interface_language').value = 'ko';
env.elements.get('interface_language').fire('change');
const failed = env.posted.at(-1);
env.scope.idolyServerReply(failed.id, {id: failed.id, ok: false, error: {message: 'Interface preference could not be saved'}});
await flush();
env.scope.idolyServerEvent({event: 'status', status: initial});
assert.equal(env.elements.get('interface_language').value, 'ko');
assert.equal(env.elements.get('language').value, 'ja');
assert.equal(env.elements.get('server-state').textContent, '실행 중');
env.elements.get('interface_language').value = 'ja';
env.elements.get('interface_language').fire('change');
const timedOut = env.posted.at(-1);
await env.tick(20000);
env.respond(timedOut, {interface_language: 'en'}); await flush();
env.scope.idolyServerEvent({event: 'status', status: initial});
assert.equal(env.elements.get('interface_language').value, 'ja');
assert.equal(env.elements.get('language').value, 'ja');
assert.equal(env.elements.get('server-state').textContent, api.translateUI('실행 중', 'ja'));
assert.equal(env.posted.filter(request => request.action === 'save_options').length, 0);
app.dispose();
""")


def test_interface_language_late_replies_cannot_repaint_hidden_or_disposed_page() -> None:
    run_js(r"""
const env = environment();
const app = api.createSettingsApp(env.scope, env.document, env.timers);
const initial = status(); initial.options.interface_language = 'en';
env.respond(env.posted[0], initial); await flush();
env.elements.get('language').value = 'ja';
env.elements.get('options-form').fire('change');
env.elements.get('interface_language').value = 'ja';
env.elements.get('interface_language').fire('change');
const hiddenRequest = env.posted.at(-1);
await env.visibility(true);
const hiddenState = ['interface_language', 'language', 'server-state', 'message'].map(id => {
  const element = env.elements.get(id); return [element.value, element.textContent, element.hidden];
});
env.respond(hiddenRequest, {interface_language: 'ko'}); await flush();
assert.deepEqual(['interface_language', 'language', 'server-state', 'message'].map(id => {
  const element = env.elements.get(id); return [element.value, element.textContent, element.hidden];
}), hiddenState);
assert.equal(env.tasks.size, 0);
await env.visibility(false);
env.respond(env.posted.at(-1), initial); await flush();
assert.equal(env.elements.get('interface_language').value, 'ja');
assert.equal(env.elements.get('language').value, 'ja');
env.elements.get('interface_language').value = 'ko';
env.elements.get('interface_language').fire('change');
const disposedRequest = env.posted.at(-1);
const lateReply = env.scope.idolyServerReply;
app.dispose();
const count = env.posted.length;
const before = env.elements.get('server-state').textContent;
lateReply(disposedRequest.id, {id: disposedRequest.id, ok: true, result: {interface_language: 'en'}});
await flush(); await env.tick(60000);
assert.equal(env.elements.get('interface_language').value, 'ko');
assert.equal(env.elements.get('server-state').textContent, before);
assert.equal(env.elements.get('language').value, 'ja');
assert.equal(env.posted.length, count);
assert.equal(env.tasks.size, 0);
""")


def test_structured_startup_error_keeps_its_message_visible() -> None:
    run_js(r"""
const env = environment(); const app = api.createSettingsApp(env.scope, env.document, env.timers);
env.respond(env.posted[0], {state: 'failed', running: false, options: status().options,
  runtime: null, last_error: {code: 'startup_failed', message: 'Local startup failed', type: 'ValueError'}});
await flush();
assert.equal(env.elements.get('server-summary').textContent, 'Local startup failed');
app.dispose();
""")


def test_graphics_choices_match_native_supported_presets_and_numeric_quality_labels() -> None:
    import re
    html = (WEB / "index.html").read_text()
    def choices(identifier):
        body = re.search(r'<select id="' + identifier + r'"[^>]*>(.*?)</select>', html).group(1)
        return re.findall(r'<option value="([^"]+)">([^<]+)</option>', body)
    assert [value for value, _ in choices('render_scale_preset')] == ['0.25', '0.5', '0.75', '1', '1.25', '1.5', '2', 'custom']
    assert [value for value, _ in choices('max_buffer_pixel_preset')] == ['720', '1080', '1440', '1920', '2560', '3840', '4096', 'custom']
    for value, label in choices('quality'):
        assert '(' + value + ')' in label
    assert 'min="0.25" max="2"' in html and 'min="256" max="4096"' in html
    assert [value for value, _ in choices('interface_language')] == ['system', 'ko', 'ja', 'en']


def test_partial_native_startup_status_keeps_interface_choice_and_forms_disabled() -> None:
    run_js(r"""
const env = environment(); env.scope.navigator = {language: 'en-US'};
const app = api.createSettingsApp(env.scope, env.document, env.timers);
env.elements.get('interface_language').value = 'ja';
env.elements.get('interface_language').fire('change');
const interfaceRequest = env.posted.at(-1);
assert.deepEqual(interfaceRequest, {id: interfaceRequest.id, action: 'save_interface_language', interface_language: 'ja'});
env.respond(interfaceRequest, {interface_language: 'ja'}); await flush();
env.respond(env.posted[0], {state: 'starting', running: false, options: {}, runtime: {}, last_error: null});
await flush();
assert.equal(env.elements.get('interface_language').value, 'ja');
assert.equal(env.elements.get('interface_language').disabled, false);
for (const name of ['options', 'presentation', 'playback', 'media']) assert.equal(env.elements.get(name+'-fields').disabled, true);
assert.equal(env.elements.get('server-state').textContent, api.translateUI('준비 중', 'ja'));
env.scope.idolyServerEvent({event: 'error', status: {state: 'failed', running: false, options: {}, runtime: {},
  last_error: {code:'not_ready', message:'The native startup error remains readable'}}});
assert.equal(env.elements.get('server-summary').textContent, 'The native startup error remains readable');
assert.equal(env.elements.get('interface_language').value, 'ja');
assert.equal(env.elements.get('resources-download').disabled, true);
app.dispose();
""")


def test_diagnostics_copy_sends_exact_visible_text_before_server_ready() -> None:
    run_js(r"""
const env = environment();
env.scope.navigator = {language:'en-US'};
Object.defineProperty(env.scope.navigator, 'clipboard', {get() { throw new Error('Browser clipboard must not be used'); }});
const visible = 'Native startup\n한글・日本語 😀\n<img src=x onerror=malicious>';
env.elements.get('diagnostics').textContent = visible;
const app = api.createSettingsApp(env.scope, env.document, env.timers);
assert.equal(env.elements.get('diagnostics-copy').disabled, false);
assert.equal(env.elements.get('options-fields').disabled, true);
env.elements.get('diagnostics-copy').fire('click');
const copy = env.posted.at(-1);
assert.deepEqual(copy, {id:copy.id, action:'diagnostics_copy', text:visible});
assert.equal(env.elements.get('diagnostics-copy').disabled, true);
env.elements.get('diagnostics-copy').fire('click');
assert.equal(env.posted.length, 2, 'Status and one explicit copy only');
env.respond(copy, {copied:true}); await flush();
assert.equal(env.elements.get('diagnostics-copy-feedback').textContent, 'Diagnostics copied.');
assert.equal(env.elements.get('diagnostics-copy-feedback').hidden, false);
assert.equal(env.elements.get('diagnostics-copy-feedback').dataset.error, 'false');
assert.equal(env.elements.get('diagnostics-copy').disabled, false);
assert.equal(env.elements.get('options-fields').disabled, true);
app.dispose();
""")


@pytest.mark.parametrize('language', ['ko', 'ja', 'en'])
def test_diagnostics_copy_failure_feedback_is_localized_and_retryable(language) -> None:
    run_js("const language = " + json.dumps(language) + r""";
const env = environment(); env.scope.navigator = {language};
const app = api.createSettingsApp(env.scope, env.document, env.timers);
env.respond(env.posted[0], {state:'failed', running:false, options:{}, runtime:{}, last_error:{message:'Startup failed'}});
await flush();
const text = env.elements.get('diagnostics').textContent;
assert.ok(text.length > 0);
assert.equal(env.elements.get('diagnostics-copy').disabled, false);
env.elements.get('diagnostics-copy').fire('click');
let copy = env.posted.at(-1);
env.scope.idolyServerReply(copy.id, {id:copy.id, ok:false, error:{message:'native failure stays out of the localized copy feedback'}});
await flush();
assert.equal(env.elements.get('diagnostics-copy-feedback').textContent,
  api.translateUI('진단을 복사하지 못했습니다. 다시 시도해 주세요.', language));
assert.equal(env.elements.get('diagnostics-copy-feedback').dataset.error, 'true');
assert.equal(env.elements.get('diagnostics-copy').disabled, false);
env.elements.get('diagnostics-copy').fire('click');
copy = env.posted.at(-1); env.respond(copy, {copied:true}); await flush();
assert.equal(env.elements.get('diagnostics-copy-feedback').textContent, api.translateUI('진단을 복사했습니다.', language));
assert.equal(env.elements.get('diagnostics-copy-feedback').dataset.error, 'false');
assert.equal(env.elements.get('diagnostics').textContent, text);
app.dispose();
""")


def test_diagnostics_copy_contract_uses_utf8_byte_limit_and_no_extra_keys() -> None:
    run_js(r"""
const env = environment(); const bridge = api.createBridge(env.scope, env.timers);
for (const payload of [{text:'가'.repeat(10923)}, {text:'😀'.repeat(8193)}, {text:'\ud800'},
  {text:'ok',path:'/private'}, {text:12}, {text:'\0'.repeat(32768)}]) await assert.rejects(bridge.request('diagnostics_copy',payload));
assert.equal(env.posted.length, 0);
for (const text of ['가'.repeat(10922)+'ab', '😀'.repeat(8192)]) {
  assert.equal(Buffer.byteLength(text,'utf8'), 32768);
  const pending = bridge.request('diagnostics_copy',{text});
  const copy = env.posted.at(-1); assert.equal(copy.text,text);
  env.respond(copy,{copied:true}); await pending;
}
bridge.dispose();
""")


def test_diagnostics_keeps_http_readiness_transfers_and_bounds_every_visible_copy_byte() -> None:
    run_js(r"""
const env = environment(); const app = api.createSettingsApp(env.scope, env.document, env.timers);
const ready = status();
ready.native = {schema:1, http_readiness:{schema:1,ok:false,transport:'NSURLSession',http_status:0,error_code:'waiting',body_is_json:false,received_bytes:0,worker_main_thread:false}};
ready.runtime.http_requests = {total_requests:8,active_requests:1,completed_requests:6,failed_requests:1,
  last_request:{request_id:8,method:'GET',path:'/client/playback',http_status:200,phase:'completed',elapsed_ms:3},recent_requests:[]};
ready.runtime.resource_transfer = {requests:4};
ready.runtime.asset_transfer = {requests:5};
ready.runtime.logs = Array.from({length:40}, (_,index)=>'行'+index+'😀한글'.repeat(230));
env.respond(env.posted[0],ready);await flush();
const text = env.elements.get('diagnostics').textContent;
assert.ok(Buffer.byteLength(text,'utf8') <= 32768);
assert.equal(Buffer.from(text,'utf8').toString('utf8'),text,'No broken surrogate pair at the display limit');
assert.ok(text.includes('http_readiness') && text.includes('NSURLSession'));
assert.ok(text.includes('http_requests') && text.includes('/client/playback'));
assert.ok(text.includes('resource_transfer') && text.includes('asset_transfer'));
assert.ok(text.includes('… 표시 한도로 나머지 진단은 생략했습니다.'));
env.elements.get('diagnostics-copy').fire('click');
const copy = env.posted.at(-1);
assert.equal(copy.action,'diagnostics_copy');assert.equal(copy.text,text);
assert.ok(Buffer.byteLength(JSON.stringify(copy),'utf8') < 65536);
env.respond(copy,{copied:true});await flush();
app.dispose();
""")


def test_diagnostic_display_is_copyable_even_with_many_escaped_control_characters() -> None:
    run_js(r"""
const env=environment();const app=api.createSettingsApp(env.scope,env.document,env.timers);
const ready=status();ready.runtime.logs=Array.from({length:40},()=>String.fromCharCode(0).repeat(1000));
env.respond(env.posted[0],ready);await flush();
const text=env.elements.get('diagnostics').textContent;
assert.ok(Buffer.byteLength(text,'utf8')<=32768);
env.elements.get('diagnostics-copy').fire('click');
const copy=env.posted.at(-1);
assert.equal(copy.action,'diagnostics_copy');assert.equal(copy.text,text);
assert.ok(Buffer.byteLength(JSON.stringify(copy),'utf8')<65536);
env.respond(copy,{copied:true});await flush();app.dispose();
""")


def test_empty_diagnostics_copy_is_disabled_without_changing_other_controls() -> None:
    run_js(r"""
const env=environment();const app=api.createSettingsApp(env.scope,env.document,env.timers);
assert.equal(env.elements.get('diagnostics').textContent,'');
assert.equal(env.elements.get('diagnostics-copy').disabled,true);
env.elements.get('diagnostics-copy').fire('click');assert.equal(env.posted.length,1);
app.dispose();
""")


def test_diagnostic_copy_preserves_consumed_unity_language_and_scoped_octo_budget() -> None:
    run_js(r"""
const env = environment(); const app = api.createSettingsApp(env.scope, env.document, env.timers);
const ready = status();
ready.native = {
  unity_host: {consumed_bundle_language: 'ja', first_warmup_verified: true},
  late_startup_calls: 2,
  octo_budget: {applied: true, scoped_local_only: true, timeout_seconds: 330},
  unrelated_private_field: 'must-not-be-copied'
};
env.respond(env.posted[0], ready); await flush();
const visible = JSON.parse(env.elements.get('diagnostics').textContent);
assert.deepEqual(visible.native.unity_host, ready.native.unity_host);
assert.equal(visible.native.late_startup_calls, 2);
assert.deepEqual(visible.native.octo_budget, ready.native.octo_budget);
assert.equal(visible.native.unrelated_private_field, undefined);
env.elements.get('diagnostics-copy').fire('click');
const copy = env.posted.at(-1); assert.equal(copy.action, 'diagnostics_copy');
const copied = JSON.parse(copy.text);
assert.equal(copied.native.unity_host.consumed_bundle_language, 'ja');
assert.equal(copied.native.unity_host.first_warmup_verified, true);
assert.deepEqual(copied.native.octo_budget, ready.native.octo_budget);
assert.equal(copy.text.includes('must-not-be-copied'), false);
env.respond(copy, {copied: true}); await flush(); app.dispose();
""")
