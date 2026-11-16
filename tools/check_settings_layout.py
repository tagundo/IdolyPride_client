#!/usr/bin/env python3
"""Owned-Actions-only actual CSS proof, using synthetic public UI state.

This serves the checked-out settings HTML/CSS/JS on one loopback socket. The
injected NativeBridge provides a synthetic read-only snapshot; no game, account
authentication or production server is started. Browser binaries/dependencies
are installed only by the explicitly pinned workflow outside project locks.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import threading
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "ios-unified/web"
CATEGORIES = ("console", "server", "users", "content", "graphics")
VIEWPORTS = ((360, 780), (844, 390), (1280, 800))
LANGUAGES = ("ko", "ja", "en")
MAX_OUTPUT = 8 * 1024 * 1024


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def public_events():
    names = None
    for node in ast.parse((ROOT / "src/idoly_local/event_settings.py").read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_EVENT_TITLES" for t in node.targets):
            names = ast.literal_eval(node.value)
    if not isinstance(names, dict):
        raise ValueError("public_label_source_missing")
    reference = json.loads((ROOT / "data/love-reference.json").read_text())["events"]
    rows = []
    for identifier, entry in sorted(reference.items()):
        catalog = entry["catalog"]
        original = catalog["name"] + " " + catalog.get("description", "")
        if identifier in names:
            ko, en = names[identifier]
            titles = {"ko": "만약 당신과 사랑에 빠진다면 · " + ko + " 편", "ja": original,
                      "en": "If I Fell in Love with You · " + en}
        else:
            titles = {"ko": "서큐×마법 ~KISS AND MAGIC!~", "ja": original, "en": "Succu × Magic ~KISS AND MAGIC!~"}
        rows.append({"id": identifier, "title": original, "titles": titles, "supported": True})
    if len(rows) != 6:
        raise ValueError("public_label_fixture_differs")
    return rows


def fixture(language):
    profile = "synthetic-layout-account-with-a-long-unbroken-slot-name-000000001"
    events = public_events()
    media = {"schema": 1, "revision": 1700000000001,
             "love_events": [{"event_id": row["id"], "start_time_ms": 0, "end_time_ms": 0} for row in events]}
    catalog = {"schema": 1, "available": True, "events": events, "ruleset_sha256": "a" * 64}
    event_state = {"schema": 1, "saved": media, "effective": media, "media_mode": True,
                   "media_default_all": True, "media_all_supported": True,
                   "invalid_settings_file": False, "restart_required": False, "catalog": catalog}
    options = {"schema": 1, "media_mode": True, "download_missing_resources": True,
               "language": "ko", "interface_language": language}
    accounts = {"action": "accounts_status", "selection_revision": "a" * 64,
                "selected": {"normal": "synthetic-normal", "media": profile},
                "accounts": [{"mode": "media", "profile": profile, "revision": "b" * 64,
                              "has_snapshot": True, "snapshot_present": True}],
                "restore_points": [], "offset": 0, "restore_offset": 0,
                "next_offset": None, "next_restore_offset": None}
    status = {"state": "ready", "running": True, "restart_required": False,
              "options": options, "effective_options": options,
              "account_management_available": True, "accounts": accounts,
              "official_import": {"state": "idle", "busy": False},
              "runtime": {"running": True, "profile": profile, "media_mode": True,
                "event_settings": event_state,
                "presentation": {"settings": {"schema": 1, "revision": 1700000000001,
                    "custom_graphics": False, "quality": 0, "target_fps": 0, "render_scale": 1,
                    "max_buffer_pixel": 4096, "anti_aliasing": -1, "shadow_resolution": 0,
                    "expand_photography": False}, "client": {"status": "waiting"}},
                "playback": {"settings": {"schema": 1, "revision": 1700000000002,
                    "wait_for_orientation": True}, "client": {"supported": True, "applied": False}},
                "media_options": {"settings": {"schema": 1, "revision": 1700000000003,
                    "hide_video_mv": False, "mv_sort": "recent", "outfit_sort": "original"}},
                "resource_library": {"catalogs": {"ios": {"available": True, "loaded": True,
                    "object_count": 54800, "total_bytes": 1073741824}}, "job": None},
                "startup_checks": {"scope": "current_run", "state": "ready", "checks": [
                    {"id": "http", "state": "ready", "code": "http_json_ready"},
                    {"id": "grpc", "state": "ready", "code": "listener_started"}]},
                "durable_history": {"available": True, "last_failure": None},
                "client_diagnostics": {"summary": "Synthetic layout fixture"},
                "logs": ["Synthetic public browser fixture; no game or official account connection."]}}
    return {"status": status, "accounts": accounts, "events": event_state}


def bridge_script(values):
    return "const layoutFixture=" + json.dumps(values, ensure_ascii=False) + r""";
window.__layoutUnexpected=[];window.__layoutActions=[];
window.webkit={messageHandlers:{idolyServer:{postMessage(request){
  const action=request&&request.action;window.__layoutActions.push(action);
  let result;
  if(action==='status')result=layoutFixture.status;
  else if(action==='accounts_status')result=layoutFixture.accounts;
  else if(action==='events_status'){
    result=JSON.parse(JSON.stringify(layoutFixture.events));result.media_mode=request.mode==='media';
    if(!result.media_mode){result.saved={schema:1,revision:0,love_events:[]};result.effective=null;result.media_default_all=false;result.media_all_supported=false;}
  }else{window.__layoutUnexpected.push(String(action).slice(0,64));return;}
  setTimeout(()=>{if(typeof window.idolyServerReply==='function')window.idolyServerReply(request.id,{id:request.id,ok:true,result});},0);
}}}};
"""


@contextmanager
def served_source():
    files = {"/" + name: (WEB / name).read_bytes() for name in ("index.html", "styles.css", "app.js")}
    if any(len(raw) > 2 * 1024 * 1024 for raw in files.values()):
        raise ValueError("web_source_bound")
    types = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/favicon.ico":
                self.send_response(204); self.end_headers(); return
            if path not in files:
                self.send_error(404); return
            raw = files[path]
            self.send_response(200)
            self.send_header("Content-Type", types[Path(path).suffix] + "; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers(); self.wfile.write(raw)
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), {name: {"bytes": len(raw), "sha256": digest(raw)} for name, raw in files.items()}
    finally:
        server.shutdown(); server.server_close(); thread.join(5)


GEOMETRY = r"""(category)=>{
 const page=document.getElementById('category-panel-'+category),width=document.documentElement.clientWidth;
 const content=Math.max(document.documentElement.scrollWidth,document.body.scrollWidth);
 const controls=Array.from(page.querySelectorAll('button,select,input[type="text"],input[type="number"],input[type="datetime-local"],summary.panel-summary,label.switch,label.event-card')).concat(Array.from(document.querySelectorAll('.category-navigation button,#interface_language,#refresh')));
 const visible=controls.map(e=>{const r=e.getBoundingClientRect();return {id:e.id||e.tagName,width:r.width,height:r.height,hidden:r.width===0||r.height===0};}).filter(r=>!r.hidden);
 const bad=visible.filter(r=>r.height<43.5||r.width<43.5).map(r=>({id:r.id,width:Math.round(r.width*100)/100,height:Math.round(r.height*100)/100}));
 return {viewport_width:width,content_width:content,visible_controls:visible.length,bad_hit_areas:bad.slice(0,12),
   open_help:Array.from(document.querySelectorAll('details.help-details,details.server-guide')).filter(e=>e.open).map(e=>e.id||e.className),
   selected:document.getElementById('category-'+category).getAttribute('aria-selected')==='true',
   layout: getComputedStyle(document.querySelector('.settings-shell')).gridTemplateColumns};
}"""


def run(output):
    from playwright.sync_api import sync_playwright
    records, screenshots, blocked, page_errors = [], [], [], []
    with served_source() as (origin, sources), sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        version = browser.version
        try:
            for language in LANGUAGES:
                for width, height in VIEWPORTS:
                    context = browser.new_context(viewport={"width": width, "height": height},
                        device_scale_factor=1, locale={"ko":"ko-KR","ja":"ja-JP","en":"en-US"}[language],
                        color_scheme="light", service_workers="block", accept_downloads=False)
                    page = context.new_page()
                    def route(request):
                        value = urlsplit(request.request.url)
                        if value.scheme + "://" + value.netloc == origin and value.path in ("/index.html", "/styles.css", "/app.js", "/favicon.ico"):
                            request.continue_()
                        else:
                            blocked.append(value.scheme + ":" + value.path[:100]); request.abort()
                    page.route("**/*", route)
                    page.on("pageerror", lambda error: page_errors.append(type(error).__name__))
                    page.add_init_script(bridge_script(fixture(language)))
                    page.goto(origin + "/index.html", wait_until="load")
                    page.wait_for_function("document.getElementById('options-fields').disabled===false && document.getElementById('events-list').children.length===6 && document.documentElement.lang==='" + language + "'", timeout=10000)
                    for identifier in ("panel-diagnostics", "panel-accounts", "panel-official", "panel-events"):
                        if page.locator("#" + identifier).evaluate("e=>e.open"):
                            raise AssertionError("default_panel_should_be_collapsed:" + identifier)
                    if not page.locator("#panel-graphics").evaluate("e=>e.open"):
                        raise AssertionError("graphics_should_be_expanded")
                    if page.locator("details.help-details").count() < 1:
                        raise AssertionError("help_disclosures_missing")
                    for category in CATEGORIES:
                        page.locator("#category-" + category).click()
                        panels = page.locator("#category-panel-" + category + " details.card-panel")
                        for index in range(panels.count()):
                            panel = panels.nth(index)
                            if not panel.evaluate("e=>e.open"):
                                panel.locator(":scope > summary").click()
                            if not panel.evaluate("e=>e.open"):
                                raise AssertionError("primary_panel_did_not_open")
                        geometry = page.evaluate(GEOMETRY, category)
                        record = {"language": language, "viewport": {"width": width, "height": height}, "category": category, **geometry}
                        records.append(record)
                        if (not geometry["selected"] or geometry["content_width"] > geometry["viewport_width"] + 2
                                or not geometry["visible_controls"] or geometry["bad_hit_areas"] or geometry["open_help"]):
                            raise AssertionError("actual_browser_layout_failed")
                        if language == "ko":
                            panels.first.locator(":scope > summary").scroll_into_view_if_needed()
                            name = str(width) + "x" + str(height) + "-" + category + ".png"
                            raw = page.screenshot(animations="disabled", caret="hide", full_page=False)
                            if len(raw) > 2 * 1024 * 1024:
                                raise ValueError("screenshot_bound")
                            (output / name).write_bytes(raw)
                            screenshots.append({"name": name, "bytes": len(raw), "sha256": digest(raw)})
                    if page.evaluate("window.__layoutUnexpected"):
                        raise AssertionError("unexpected_native_mutation_request")
                    context.close()
        except Exception:
            observation = {"schema": 1, "status": "FAIL", "scope": "synthetic-readonly-browser-layout",
                           "source_commit": os.environ["GITHUB_SHA"], "cases": records,
                           "blocked_requests": blocked, "page_error_types": page_errors}
            (output / "failure-observation.json").write_text(json.dumps(observation, ensure_ascii=False, indent=2) + "\n")
            if "page" in locals() and not page.is_closed():
                raw = page.screenshot(animations="disabled", caret="hide", full_page=False)
                if len(raw) <= 2 * 1024 * 1024:
                    (output / "failure-viewport.png").write_bytes(raw)
            raise
        finally:
            browser.close()
    if len(records) != 45 or blocked or page_errors:
        raise AssertionError("layout_case_inventory_or_network_error")
    return {"schema": 1, "status": "PASS", "scope": "actual-Chromium-settings-CSS-with-synthetic-readonly-native-bridge",
            "native_gameplay_tested": False, "official_authentication_performed": False,
            "browser": {"engine": "chromium", "version": version,
                        "playwright": importlib.metadata.version("playwright")},
            "source_commit": os.environ["GITHUB_SHA"], "source_files": sources,
            "cases": records, "screenshots": screenshots}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true" or not re.fullmatch(r"[0-9a-f]{40}", os.environ.get("GITHUB_SHA", "")):
        raise SystemExit("layout_probe_requires_owned_actions")
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    output = args.output
    if (not output.is_absolute() or output.is_symlink() or output.exists()
            or not output.parent.resolve(strict=True).is_relative_to(temporary)):
        raise SystemExit("layout_probe_requires_fresh_owned_output")
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() != os.environ["GITHUB_SHA"]:
        raise SystemExit("layout_probe_source_differs")
    output.mkdir(mode=0o700)
    try:
        report = run(output)
    except Exception as error:
        (output / "layout-failure.json").write_text(json.dumps({"schema": 1, "status": "FAIL", "error_type": type(error).__name__}) + "\n")
        raise
    (output / "layout-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if sum(path.stat().st_size for path in output.iterdir()) > MAX_OUTPUT:
        raise SystemExit("layout_proof_bound")
    print(json.dumps({"status": report["status"], "cases": len(report["cases"]), "screenshots": len(report["screenshots"])}))


if __name__ == "__main__":
    main()
