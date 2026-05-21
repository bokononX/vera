"""Local web GUI surface for Vera observability snapshots."""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional, Protocol
from urllib.parse import parse_qs, urlparse

from .observability import ConsoleSnapshot, snapshot_to_json


class ObservabilityProvider(Protocol):
    def snapshot(
        self,
        focused_agent_id: Optional[str] = None,
        event_filter: Optional[str] = None,
        event_limit: int = 200,
    ) -> ConsoleSnapshot:
        """Return the latest console state."""


def run_gui(
    provider: ObservabilityProvider,
    host: str = "127.0.0.1",
    port: int = 8765,
    smoke: bool = False,
) -> int:
    """Serve the local Vera console GUI. Smoke mode verifies routes and exits."""

    server = _build_server(provider, host, port)
    actual_host, actual_port = server.server_address
    display_host = "127.0.0.1" if actual_host in {"0.0.0.0", "::"} else actual_host
    url = "http://{}:{}".format(display_host, actual_port)
    if smoke:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(url + "/api/state", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if "agents" not in payload or "budget" not in payload:
                raise RuntimeError("GUI state payload is missing required keys")
            with urllib.request.urlopen(url + "/", timeout=5) as response:
                html = response.read().decode("utf-8")
            if "Vera Agent Console" not in html:
                raise RuntimeError("GUI HTML did not render the console shell")
        finally:
            server.shutdown()
            server.server_close()
        print("Vera GUI smoke OK: {}".format(url))
        return 0

    print("Vera GUI listening on {}".format(url))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0


def _build_server(
    provider: ObservabilityProvider,
    host: str,
    port: int,
) -> ThreadingHTTPServer:
    handler = _handler_factory(provider)
    return ThreadingHTTPServer((host, port), handler)


def _handler_factory(provider: ObservabilityProvider) -> Callable[..., BaseHTTPRequestHandler]:
    class VeraConsoleHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_text(_HTML, content_type="text/html; charset=utf-8")
                return
            if parsed.path == "/api/state":
                params = parse_qs(parsed.query)
                focus = _first(params.get("focus"))
                event_filter = _first(params.get("filter"))
                payload = snapshot_to_json(
                    provider.snapshot(
                        focused_agent_id=focus,
                        event_filter=event_filter,
                    )
                )
                self._send_json(payload)
                return
            self.send_error(404, "not found")

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_json(self, payload: object) -> None:
            body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, text: str, content_type: str) -> None:
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return VeraConsoleHandler


def _first(values: Optional[list[str]]) -> Optional[str]:
    if not values:
        return None
    value = values[0].strip()
    return value or None


_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vera Agent Console</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f7f4;
      --panel: #ffffff;
      --ink: #1d2528;
      --muted: #667276;
      --line: #d8dddc;
      --accent: #0c6b58;
      --warn: #a45013;
      --bad: #a53337;
      --code: #263238;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.4 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 2;
      border-bottom: 1px solid var(--line);
      background: rgba(247, 247, 244, 0.96);
      padding: 10px 16px;
    }
    h1 {
      margin: 0 0 8px;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0;
    }
    .budget {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      font-size: 13px;
    }
    .pill {
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 5px 8px;
      border-radius: 6px;
      min-height: 28px;
    }
    main {
      display: grid;
      grid-template-columns: minmax(280px, 34%) 1fr;
      gap: 0;
      min-height: calc(100vh - 72px);
    }
    aside {
      border-right: 1px solid var(--line);
      padding: 14px;
      overflow: auto;
    }
    section {
      padding: 14px;
      overflow: auto;
    }
    h2 {
      margin: 0 0 10px;
      font-size: 13px;
      text-transform: uppercase;
      color: var(--muted);
      letter-spacing: 0;
    }
    button, input {
      font: inherit;
    }
    .agent {
      width: 100%;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 4px 8px;
      text-align: left;
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 9px;
      border-radius: 6px;
      margin: 0 0 8px;
      cursor: pointer;
    }
    .agent[aria-pressed="true"] {
      border-color: var(--accent);
      outline: 2px solid rgba(12, 107, 88, 0.14);
    }
    .agent strong { font-size: 13px; overflow-wrap: anywhere; }
    .meta { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
    .status { font-weight: 700; color: var(--accent); }
    .status.failed, .status.blocked { color: var(--bad); }
    .split {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }
    .plain-panel {
      border-bottom: 1px solid var(--line);
      padding-bottom: 14px;
      margin-bottom: 14px;
    }
    .summary {
      margin: 0 0 8px;
      color: var(--code);
      overflow-wrap: anywhere;
    }
    .plan {
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .plan li {
      border-left: 3px solid var(--line);
      padding: 4px 0 4px 8px;
      margin-bottom: 5px;
    }
    .plan .agent_generated { border-color: var(--accent); }
    .plan .user_confirmed { border-color: #4c6f91; }
    .plan .blocker { border-color: var(--warn); }
    .toolbar {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }
    .toolbar button {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      padding: 6px 9px;
      cursor: pointer;
    }
    .toolbar button[aria-pressed="true"] {
      border-color: var(--accent);
      color: var(--accent);
      font-weight: 700;
    }
    .toolbar input {
      min-width: 180px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 8px;
    }
    .events {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .event {
      border-top: 1px solid var(--line);
      padding: 7px 0;
    }
    .event .error { color: var(--bad); }
    .empty { color: var(--muted); }
    @media (max-width: 820px) {
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      .split { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Vera Agent Console</h1>
    <div class="budget" id="budget"></div>
  </header>
  <main>
    <aside>
      <h2>Available agents</h2>
      <div id="agents"></div>
    </aside>
    <section>
      <div class="plain-panel">
        <h2>Last turn and current plan</h2>
        <div id="focus"></div>
      </div>
      <div>
        <h2>Agent log stream</h2>
        <div class="toolbar">
          <button id="pause" type="button" aria-pressed="false">Pause</button>
          <button id="follow" type="button" aria-pressed="true">Follow</button>
          <input id="filter" type="search" placeholder="Filter events">
        </div>
        <div class="events" id="events"></div>
      </div>
    </section>
  </main>
  <script>
    const state = { focus: null, paused: false, follow: true, last: null };
    const $ = (id) => document.getElementById(id);
    $("pause").addEventListener("click", () => {
      state.paused = !state.paused;
      $("pause").setAttribute("aria-pressed", String(state.paused));
      if (!state.paused) refresh();
    });
    $("follow").addEventListener("click", () => {
      state.follow = !state.follow;
      $("follow").setAttribute("aria-pressed", String(state.follow));
    });
    $("filter").addEventListener("input", () => refresh());

    function esc(value) {
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#039;"
      }[ch]));
    }
    function money(value) { return value == null ? "unknown" : Number(value).toFixed(2); }
    function age(seconds) {
      if (seconds < 60) return `${seconds}s`;
      const minutes = Math.floor(seconds / 60);
      if (minutes < 60) return `${minutes}m`;
      return `${Math.floor(minutes / 60)}h`;
    }
    async function refresh() {
      if (state.paused && state.last) return;
      const params = new URLSearchParams();
      if (state.focus) params.set("focus", state.focus);
      const filter = $("filter").value.trim();
      if (filter) params.set("filter", filter);
      const response = await fetch(`/api/state?${params.toString()}`, { cache: "no-store" });
      state.last = await response.json();
      render(state.last);
    }
    function render(data) {
      $("budget").innerHTML = `
        <span class="pill">${esc(data.budget.summary)}</span>
        <span class="pill">${esc(data.budget.rate_limits.note)}</span>
        <span class="pill">${esc(data.budget.usage.note)}</span>
      `;
      $("agents").innerHTML = data.agents.length ? data.agents.map((agent) => `
        <button class="agent" type="button" data-agent="${esc(agent.agent_id)}" aria-pressed="${agent.agent_id === data.focused_agent_id}">
          <strong>${esc(agent.task_id)}</strong>
          <span class="status ${esc(agent.status)}">${esc(agent.status)}</span>
          <span class="meta">${esc(agent.source_channel)} turn ${esc(agent.current_turn)} age ${age(agent.age_seconds)}</span>
          <span class="meta">${esc(agent.token_usage ?? "unknown")} tok / $${money(agent.budget_usd)}</span>
          <span class="meta" style="grid-column: 1 / -1">identity ${esc(agent.session_identity_label ?? "unknown session identity")}</span>
          <span class="meta" style="grid-column: 1 / -1">${esc(agent.workspace_path ?? "unknown workspace")}</span>
        </button>`).join("") : `<p class="empty">none</p>`;
      document.querySelectorAll(".agent").forEach((button) => {
        button.addEventListener("click", () => {
          state.focus = button.dataset.agent;
          refresh();
        });
      });
      if (!data.focused) {
        $("focus").innerHTML = `<p class="empty">no focused agent</p>`;
      } else {
        $("focus").innerHTML = `
          <p class="summary"><strong>Last:</strong> ${esc(data.focused.last_turn_summary)}</p>
          <p class="summary"><strong>Objective:</strong> ${esc(data.focused.current_objective)}</p>
          <ul class="plan">${data.focused.plan.map((item) => `
            <li class="${esc(item.origin)}">${item.done ? "x" : " "} ${esc(item.origin)}: ${esc(item.text)}</li>
          `).join("")}</ul>
        `;
      }
      $("events").innerHTML = data.events.length ? data.events.map((event) => `
        <div class="event">
          <span class="${esc(event.severity)}">${esc(event.created_at)} ${esc(event.category)} ${esc(event.event_type)}</span>
          turn ${esc(event.turn_number ?? "unknown")} ${esc(event.summary)}
          ${event.details && Object.keys(event.details).length ? "\\n" + esc(JSON.stringify(event.details)) : ""}
        </div>
      `).join("") : `<p class="empty">none</p>`;
      if (state.follow) window.scrollTo(0, document.body.scrollHeight);
    }
    refresh();
    setInterval(refresh, 1500);
  </script>
</body>
</html>
"""
