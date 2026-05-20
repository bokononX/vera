"""Terminal console surface for Vera observability snapshots."""

from __future__ import annotations

import curses
import time
from typing import Optional, Protocol

from .observability import ConsoleSnapshot, format_budget_bar


class ObservabilityProvider(Protocol):
    def snapshot(
        self,
        focused_agent_id: Optional[str] = None,
        event_filter: Optional[str] = None,
        event_limit: int = 200,
    ) -> ConsoleSnapshot:
        """Return the latest console state."""


def render_tui_frame(
    snapshot: ConsoleSnapshot,
    width: int = 120,
    height: int = 40,
    paused: bool = False,
    follow: bool = True,
    scroll_offset: int = 0,
) -> str:
    """Render a deterministic terminal frame for smoke tests and curses output."""

    usable_width = max(40, width)
    lines = [
        _clip("Vera Agent Console   {}".format(format_budget_bar(snapshot.budget)), usable_width),
        _clip(
            "state: {} agents: {} focus: {} stream: {} follow: {}".format(
                snapshot.generated_at,
                len(snapshot.agents),
                snapshot.focused_agent_id or "none",
                "paused" if paused else "live",
                "on" if follow else "off",
            ),
            usable_width,
        ),
        "",
        "Available agents",
    ]
    if not snapshot.agents:
        lines.append("  none")
    for agent in snapshot.agents:
        selected = ">" if agent.agent_id == snapshot.focused_agent_id else " "
        usage = "{} tok / ${}".format(
            _display(agent.token_usage),
            _money(agent.budget_usd),
        )
        lines.append(
            _clip(
                "{} {:<13} {:<9} turn {:<3} age {:<6} task {} workspace {} usage {}".format(
                    selected,
                    agent.status,
                    agent.source_channel,
                    agent.current_turn,
                    _age(agent.age_seconds),
                    agent.task_id,
                    agent.workspace_path or "unknown",
                    usage,
                ),
                usable_width,
            )
        )

    lines.extend(["", "Last turn and current plan"])
    if snapshot.focused is None:
        lines.append("  no focused agent")
    else:
        focused = snapshot.focused
        lines.append(_clip("  last: {}".format(focused.last_turn_summary), usable_width))
        lines.append(_clip("  objective: {}".format(focused.current_objective), usable_width))
        for item in focused.plan:
            marker = "x" if item.done else " "
            lines.append(_clip("  [{}] {}: {}".format(marker, item.origin.value, item.text), usable_width))
        for blocker in focused.blockers:
            lines.append(_clip("  blocker: {}".format(blocker), usable_width))

    lines.extend(["", "Agent log stream"])
    events = list(snapshot.events)
    if scroll_offset > 0:
        events = events[: max(0, len(events) - scroll_offset)]
    stream_height = max(4, height - len(lines) - 1)
    events = events[-stream_height:]
    if not events:
        lines.append("  none")
    for event in events:
        details = ""
        if event.details:
            details = " {}".format(_compact_details(event.details))
        lines.append(
            _clip(
                "  {} {:<8} {:<18} turn {:<3} {}".format(
                    _time_part(event.created_at),
                    event.category.value,
                    event.event_type,
                    _display(event.turn_number),
                    event.summary + details,
                ),
                usable_width,
            )
        )
    return "\n".join(lines[:height])


def run_tui(
    provider: ObservabilityProvider,
    focused_agent_id: Optional[str] = None,
    event_filter: Optional[str] = None,
    refresh_seconds: float = 1.0,
    smoke: bool = False,
) -> int:
    """Run the terminal console. Smoke mode renders one frame and exits."""

    if smoke:
        snapshot = provider.snapshot(focused_agent_id=focused_agent_id, event_filter=event_filter)
        print(render_tui_frame(snapshot))
        print("Vera TUI smoke OK")
        return 0
    return curses.wrapper(
        _run_curses,
        provider,
        focused_agent_id,
        event_filter,
        refresh_seconds,
    )


def _run_curses(
    stdscr: "curses._CursesWindow",
    provider: ObservabilityProvider,
    focused_agent_id: Optional[str],
    event_filter: Optional[str],
    refresh_seconds: float,
) -> int:
    curses.curs_set(0)
    stdscr.nodelay(True)
    paused = False
    follow = True
    scroll_offset = 0
    focus_index = 0
    active_focus = focused_agent_id
    cached_snapshot = provider.snapshot(focused_agent_id=active_focus, event_filter=event_filter)

    while True:
        if not paused:
            cached_snapshot = provider.snapshot(focused_agent_id=active_focus, event_filter=event_filter)
            active_focus = cached_snapshot.focused_agent_id
            for index, agent in enumerate(cached_snapshot.agents):
                if agent.agent_id == active_focus:
                    focus_index = index
                    break
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        frame = render_tui_frame(
            cached_snapshot,
            width=width,
            height=height,
            paused=paused,
            follow=follow,
            scroll_offset=scroll_offset,
        )
        for line_number, line in enumerate(frame.splitlines()[:height]):
            stdscr.addstr(line_number, 0, line[: max(0, width - 1)])
        stdscr.refresh()

        deadline = time.monotonic() + refresh_seconds
        while time.monotonic() < deadline:
            key = stdscr.getch()
            if key == -1:
                time.sleep(0.05)
                continue
            if key in (ord("q"), 27):
                return 0
            if key == ord("p"):
                paused = not paused
            elif key == ord("f"):
                follow = not follow
                if follow:
                    scroll_offset = 0
            elif key in (curses.KEY_DOWN, ord("j")) and cached_snapshot.agents:
                focus_index = min(focus_index + 1, len(cached_snapshot.agents) - 1)
                active_focus = cached_snapshot.agents[focus_index].agent_id
            elif key in (curses.KEY_UP, ord("k")) and cached_snapshot.agents:
                focus_index = max(focus_index - 1, 0)
                active_focus = cached_snapshot.agents[focus_index].agent_id
            elif key == curses.KEY_NPAGE:
                follow = False
                scroll_offset += 10
            elif key == curses.KEY_PPAGE:
                scroll_offset = max(0, scroll_offset - 10)
                if scroll_offset == 0:
                    follow = True


def _clip(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 1:
        return ""
    return text[: width - 1]


def _display(value: object) -> str:
    if value is None:
        return "unknown"
    return str(value)


def _money(value: Optional[float]) -> str:
    if value is None:
        return "unknown"
    return "{:.2f}".format(value)


def _age(seconds: int) -> str:
    if seconds < 60:
        return "{}s".format(seconds)
    minutes = seconds // 60
    if minutes < 60:
        return "{}m".format(minutes)
    return "{}h".format(minutes // 60)


def _time_part(value: str) -> str:
    if "T" in value:
        return value.split("T", 1)[1][:8]
    return value[:8]


def _compact_details(details: object) -> str:
    text = str(details)
    return text if len(text) <= 160 else text[:157] + "..."
