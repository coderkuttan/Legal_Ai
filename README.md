# SENTINEL — Legal Compliance Drone (FOL Airspace Agent)

**Track 3 · Unit 4 — First-Order Logic Agent**

A simulated national-security surveillance drone that reasons about airspace
legality with a real First-Order Logic knowledge base — forward and backward
chaining over Horn-clause rules, not hardcoded `if/else` — before it is
allowed to enter any grid zone.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Files (each is one phase of the pipeline)

| File | Phase | Responsibility |
|---|---|---|
| [`fol_engine.py`](fol_engine.py) | 1 — Reasoning core | Generic, domain-agnostic FOL engine: `Variable`, `Atom`, `Rule`, unification, forward chaining (fixpoint over Horn clauses), backward chaining (SLD-style resolution with a full proof trace). |
| [`airspace_kb.py`](airspace_kb.py) | 2 — Knowledge base | Domain predicates (`Restricted`, `SafeZone`, `ControlledZone`, `TemporaryRestricted`, `Corridor`, `HasPermit`, `NoPermit`, `FlyOver`) and the compliance rules `R1`–`R7`. Owns fact mutation (grant/revoke permit, declare/lift NOTAM) and the explainable `query_flyover()` API. |
| [`grid_world.py`](grid_world.py) | 3 — Environment | The 8×8 zone map/layout and BFS pathfinding that treats any FOL-denied zone as impassable. |
| [`drone_agent.py`](drone_agent.py) | 4 — Mission agent | The state machine: plan → pause & query before every zone entry → move / reroute / intercept → capture → return → complete. |
| [`app.py`](app.py) | 5 — UI | Streamlit "mission control" dashboard: live 2D map, explainable inference panel, event/inference log, permit & NOTAM controls, manual override, KB explorer. |

## Rules implemented

```
Restricted(x) ∧ NoPermit(drone,x)      → ¬FlyOver(drone,x)      (R1)
Restricted(x) ∧ HasPermit(drone,x)     → FlyOver(drone,x)       (R2)
SafeZone(x) ∧ Drone(drone)             → FlyOver(drone,x)       (R3)
TemporaryRestricted(x) ∧ Drone(drone)  → ¬FlyOver(drone,x)      (R4)
Corridor(x) ∧ Drone(drone)             → FlyOver(drone,x)       (R5)
ControlledZone(x) ∧ HasPermit(drone,x) → FlyOver(drone,x)       (R6)
ControlledZone(x) ∧ NoPermit(drone,x)  → ¬FlyOver(drone,x)      (R7)
```

`Drone(drone)` is included in R3–R5 so every rule is "safe" (every head
variable is bound by a body atom) — required for forward chaining over a
function-free FOL / Datalog fragment to terminate correctly.

Denial rules are checked before authorization rules (safety takes
precedence), and an unknown zone with no matching rule defaults to
**DENIED** (closed-world, fail-safe).

## Demo checklist

- **Step** through a mission to see the drone pause and print facts / rule
  matched / substitution / proof / decision before every zone entry.
- Declare a **NOTAM** on the drone's next planned zone mid-mission to watch
  it get denied and automatically reroute.
- Grant/revoke a **permit** for a restricted or controlled zone and re-run a
  manual query to see the rule (and decision) flip.
- Check **manual override** then Step into a denied zone to trigger a
  simulated interception and mission failure.
