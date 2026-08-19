"""
Phase 4 - Drone Mission Agent
=============================
The mission state machine. Wires the FOL knowledge base (airspace_kb) to the
grid world (grid_world) and drives a single drone from a start zone to a
surveillance target and back to base - pausing to run an FOL query before
every zone entry, rerouting around denials, and handling manual overrides.

No FOL reasoning and no grid math live here; this module only sequences them.
"""

from dataclasses import dataclass, field

from airspace_kb import AirspaceKB, InferenceResult, DRONE_ID
from grid_world import bfs_path

PHASE_PLANNING = "PLANNING"
PHASE_TO_TARGET = "EN_ROUTE_TO_TARGET"
PHASE_CAPTURING = "CAPTURING"
PHASE_RETURNING = "RETURNING"
PHASE_COMPLETE = "COMPLETE"
PHASE_FAILED = "FAILED"
PHASE_INTERCEPTED = "INTERCEPTED"


@dataclass
class LogEvent:
    step: int
    kind: str          # QUERY, MOVE, PAUSE, DENIED, REROUTE, CAPTURE, OVERRIDE, INTERCEPTED, INFO, COMPLETE, FAILED
    message: str
    inference: InferenceResult = None


class Mission:
    def __init__(self, kb: AirspaceKB, start: str, target: str, base: str = None):
        self.kb = kb
        self.start = start
        self.target = target
        self.base = base or start
        self.drone = DRONE_ID

        self.position = start
        self.phase = PHASE_PLANNING
        self.path: list = []
        self.path_index = 0
        self.step_count = 0
        self.log: list[LogEvent] = []
        self.last_inference: InferenceResult = None
        self.pending_move: str = None
        self.awaiting_decision = False

        self._emit("INFO", f"Mission created. Start={start}, Target={target}, Base={self.base}.")
        self._plan_route(self.position, self.target, PHASE_TO_TARGET)

    # -- logging ----------------------------------------------------------

    def _emit(self, kind, message, inference=None):
        self.step_count += 1
        self.log.append(LogEvent(self.step_count, kind, message, inference))

    # -- route planning -----------------------------------------------------

    def _plan_route(self, origin, destination, next_phase):
        legal_map = self.kb.forward_map(self.drone)
        blocked = {z for z, decision in legal_map.items() if decision == "DENIED"}
        blocked.discard(origin)
        path = bfs_path(origin, destination, blocked)
        if path is None:
            self._emit("FAILED", f"No legal route exists from {origin} to {destination}. Mission blocked.")
            self.phase = PHASE_FAILED
            return
        self.path = path
        self.path_index = 0
        self.phase = next_phase
        self._emit("INFO", f"Route planned: {' -> '.join(path)}")

    def is_finished(self):
        return self.phase in (PHASE_COMPLETE, PHASE_FAILED, PHASE_INTERCEPTED)

    # -- one simulation step -------------------------------------------------

    def step(self, override=False):
        """Advance the mission by one zone-transition. Call repeatedly (or in
        a loop) to run the mission. `override` forces entry into the next
        zone even if the FOL query denies it (for the manual-override demo)."""
        if self.is_finished():
            return

        if self.phase == PHASE_CAPTURING:
            self._emit("CAPTURE", f"Surveillance imagery captured at {self.position}.")
            self._plan_route(self.position, self.base, PHASE_RETURNING)
            return

        if self.path_index + 1 >= len(self.path):
            # Reached the end of the current leg.
            if self.phase == PHASE_TO_TARGET:
                self.phase = PHASE_CAPTURING
                self._emit("INFO", f"Arrived at surveillance target {self.position}.")
            elif self.phase == PHASE_RETURNING:
                self.phase = PHASE_COMPLETE
                self._emit("COMPLETE", f"Drone landed safely at base {self.position}. Mission complete.")
            return

        next_zone = self.path[self.path_index + 1]
        self._emit("PAUSE", f"Pausing before entering {next_zone}. Executing FOL query...")
        result = self.kb.query_flyover(self.drone, next_zone)
        self.last_inference = result
        self._emit("QUERY", f"FlyOver({self.drone}, {next_zone}) -> {result.decision}", result)

        if result.authorized:
            self.position = next_zone
            self.path_index += 1
            self._emit("MOVE", f"Entered {next_zone} (legally authorized).")
            return

        if override:
            self._emit("OVERRIDE", f"MANUAL OVERRIDE: forcing entry into {next_zone} despite denial.")
            self.position = next_zone
            self.path_index += 1
            self._emit(
                "INTERCEPTED",
                f"Unauthorized entry detected in {next_zone}. Interception triggered by air-defense system.",
            )
            self.phase = PHASE_INTERCEPTED
            self._emit("FAILED", "Mission failed: drone intercepted after unauthorized airspace violation.")
            return

        # Denied, no override: reroute around this zone.
        self._emit("DENIED", f"Entry into {next_zone} denied. Searching for an alternative legal route.")
        legal_map = self.kb.forward_map(self.drone)
        blocked = {z for z, decision in legal_map.items() if decision == "DENIED"}
        blocked.discard(self.position)
        destination = self.target if self.phase == PHASE_TO_TARGET else self.base
        new_path = bfs_path(self.position, destination, blocked)
        if new_path is None or len(new_path) < 2:
            self._emit("FAILED", f"No alternative legal route from {self.position} to {destination}. Mission blocked.")
            self.phase = PHASE_FAILED
            return
        self.path = new_path
        self.path_index = 0
        self._emit("REROUTE", f"Alternative legal route found: {' -> '.join(new_path)}")

    def run_to_completion(self, max_steps=500):
        n = 0
        while not self.is_finished() and n < max_steps:
            self.step()
            n += 1
