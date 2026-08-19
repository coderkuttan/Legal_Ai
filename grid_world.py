"""
Phase 3 - Grid World
====================
The 2D airspace map: zone layout, coordinate<->name helpers, and BFS
pathfinding that treats any zone the FOL engine currently denies as
impassable. Pure grid/graph logic - no FOL reasoning lives here.
"""

from collections import deque
from dataclasses import dataclass

COLS = "ABCDEFGH"   # 8 columns
ROWS = list(range(1, 9))  # 8 rows -> 64 zones

ZONE_COLORS = {
    "safe": "#2ecc71",
    "controlled": "#f1c40f",
    "restricted": "#e74c3c",
    "corridor": "#3498db",
}
TEMP_RESTRICTED_COLOR = "#e67e22"


def zone_name(col: int, row: int) -> str:
    return f"{COLS[col]}{ROWS[row]}"


def zone_coords(name: str):
    col = COLS.index(name[0])
    row = ROWS.index(int(name[1:]))
    return col, row


@dataclass(frozen=True)
class Zone:
    name: str
    col: int
    row: int
    ztype: str


def build_default_grid() -> dict:
    """Returns {zone_name: ztype}. Layout:
    - A defense cluster of Restricted zones in the center (guarded base).
    - A ring of Controlled zones around it.
    - A diagonal Corridor of pre-authorized transit zones.
    - Everything else is a SafeZone.
    """
    zones = {}
    restricted_cells = {(3, 3), (3, 4), (4, 3), (4, 4)}
    controlled_cells = {
        (2, 2), (2, 3), (2, 4), (2, 5),
        (5, 2), (5, 3), (5, 4), (5, 5),
        (3, 2), (4, 2), (3, 5), (4, 5),
    }
    corridor_cells = {(i, i) for i in range(8) if (i, i) not in restricted_cells
                       and (i, i) not in controlled_cells}

    for col in range(8):
        for row in range(8):
            cell = (col, row)
            if cell in restricted_cells:
                ztype = "restricted"
            elif cell in controlled_cells:
                ztype = "controlled"
            elif cell in corridor_cells:
                ztype = "corridor"
            else:
                ztype = "safe"
            zones[zone_name(col, row)] = ztype
    return zones


def neighbors(name: str):
    col, row = zone_coords(name)
    candidates = [(col + 1, row), (col - 1, row), (col, row + 1), (col, row - 1)]
    result = []
    for c, r in candidates:
        if 0 <= c < 8 and 0 <= r < 8:
            result.append(zone_name(c, r))
    return result


def bfs_path(start: str, goal: str, blocked: set) -> list | None:
    """Shortest path (list of zone names, start..goal inclusive) avoiding
    zones in `blocked`. `start` itself is never treated as blocked."""
    if start == goal:
        return [start]
    frontier = deque([start])
    came_from = {start: None}
    while frontier:
        current = frontier.popleft()
        for nxt in neighbors(current):
            if nxt in came_from:
                continue
            if nxt in blocked:
                continue
            came_from[nxt] = current
            if nxt == goal:
                path = [nxt]
                while came_from[path[-1]] is not None:
                    path.append(came_from[path[-1]])
                return list(reversed(path))
            frontier.append(nxt)
    return None
