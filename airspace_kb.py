"""
Phase 2 - Airspace Knowledge Base
=================================
Defines the drone/airspace predicates, the compliance rules from the brief,
and a small API for mutating facts (grant/revoke permits, declare/lift
temporary restrictions) and for running an explainable FlyOver query.

    Restricted(x) ∧ NoPermit(drone,x)        → ¬FlyOver(drone,x)
    Restricted(x) ∧ HasPermit(drone,x)       → FlyOver(drone,x)
    SafeZone(x)                              → FlyOver(drone,x)
    TemporaryRestricted(x)                   → ¬FlyOver(drone,x)
    Corridor(x)                              → FlyOver(drone,x)
    ControlledZone(x) ∧ HasPermit(drone,x)   → FlyOver(drone,x)
    ControlledZone(x) ∧ NoPermit(drone,x)    → ¬FlyOver(drone,x)
"""

from dataclasses import dataclass, field
from fol_engine import Atom, Rule, Variable, KnowledgeBase, forward_chain, backward_chain

# Predicate names
RESTRICTED = "Restricted"
SAFE_ZONE = "SafeZone"
CONTROLLED_ZONE = "ControlledZone"
TEMP_RESTRICTED = "TemporaryRestricted"
CORRIDOR = "Corridor"
HAS_PERMIT = "HasPermit"
NO_PERMIT = "NoPermit"
FLY_OVER = "FlyOver"
DRONE_PRED = "Drone"

DRONE_ID = "Drone1"

ZONE_PREDICATE = {
    "safe": SAFE_ZONE,
    "controlled": CONTROLLED_ZONE,
    "restricted": RESTRICTED,
    "corridor": CORRIDOR,
}

_d, _x = Variable("drone"), Variable("x")

RULES = [
    Rule("R1", (Atom(RESTRICTED, (_x,)), Atom(NO_PERMIT, (_d, _x))),
         Atom(FLY_OVER, (_d, _x), positive=False),
         "A restricted zone denies fly-over unless the drone holds a permit."),
    Rule("R2", (Atom(RESTRICTED, (_x,)), Atom(HAS_PERMIT, (_d, _x))),
         Atom(FLY_OVER, (_d, _x), positive=True),
         "A restricted zone permits fly-over if the drone holds a permit."),
    Rule("R3", (Atom(SAFE_ZONE, (_x,)), Atom(DRONE_PRED, (_d,))),
         Atom(FLY_OVER, (_d, _x), positive=True),
         "Safe zones are always open to fly-over."),
    Rule("R4", (Atom(TEMP_RESTRICTED, (_x,)), Atom(DRONE_PRED, (_d,))),
         Atom(FLY_OVER, (_d, _x), positive=False),
         "A temporary restriction (NOTAM) always denies fly-over."),
    Rule("R5", (Atom(CORRIDOR, (_x,)), Atom(DRONE_PRED, (_d,))),
         Atom(FLY_OVER, (_d, _x), positive=True),
         "Authorized flight corridors are always open to fly-over."),
    Rule("R6", (Atom(CONTROLLED_ZONE, (_x,)), Atom(HAS_PERMIT, (_d, _x))),
         Atom(FLY_OVER, (_d, _x), positive=True),
         "A controlled zone permits fly-over if the drone holds a permit."),
    Rule("R7", (Atom(CONTROLLED_ZONE, (_x,)), Atom(NO_PERMIT, (_d, _x))),
         Atom(FLY_OVER, (_d, _x), positive=False),
         "A controlled zone denies fly-over without a permit."),
]


@dataclass
class InferenceResult:
    query_text: str
    drone: str
    zone: str
    facts_considered: list
    rule_matched: str
    substitution: str
    proof_lines: list
    authorized: bool
    decision: str          # "AUTHORIZED", "DENIED", "DENIED (default - no rule authorizes entry)"


class AirspaceKB:
    def __init__(self, zones: dict):
        """zones: {zone_name: zone_type} where zone_type in ZONE_PREDICATE
        for safe/controlled/restricted/corridor. Temporary restrictions are
        layered on top dynamically and are independent of the base type."""
        self.kb = KnowledgeBase()
        self.zone_types = dict(zones)
        self.temp_restricted = set()
        for rule in RULES:
            self.kb.tell_rule(rule)
        for name, ztype in zones.items():
            pred = ZONE_PREDICATE[ztype]
            self.kb.tell_fact(Atom(pred, (name,)))
        # Register the drone and default it to having no permit anywhere;
        # grant_permit() later retracts NoPermit and asserts HasPermit.
        self.kb.tell_fact(Atom(DRONE_PRED, (DRONE_ID,)))
        for name in zones:
            self.kb.tell_fact(Atom(NO_PERMIT, (DRONE_ID, name)))

    # -- fact mutation --------------------------------------------------

    def grant_permit(self, drone: str, zone: str):
        self.kb.retract_fact(Atom(NO_PERMIT, (drone, zone)))
        self.kb.tell_fact(Atom(HAS_PERMIT, (drone, zone)))

    def revoke_permit(self, drone: str, zone: str):
        self.kb.retract_fact(Atom(HAS_PERMIT, (drone, zone)))
        self.kb.tell_fact(Atom(NO_PERMIT, (drone, zone)))

    def has_permit(self, drone: str, zone: str) -> bool:
        return Atom(HAS_PERMIT, (drone, zone)) in self.kb.facts

    def declare_temp_restriction(self, zone: str):
        self.temp_restricted.add(zone)
        self.kb.tell_fact(Atom(TEMP_RESTRICTED, (zone,)))

    def lift_temp_restriction(self, zone: str):
        self.temp_restricted.discard(zone)
        self.kb.retract_fact(Atom(TEMP_RESTRICTED, (zone,)))

    # -- queries ----------------------------------------------------------

    def query_flyover(self, drone: str, zone: str) -> InferenceResult:
        """Backward-chain FlyOver(drone, zone). Denial rules are checked
        first (safety takes precedence over convenience)."""
        deny_goal = Atom(FLY_OVER, (drone, zone), positive=False)
        allow_goal = Atom(FLY_OVER, (drone, zone), positive=True)

        proved_deny, deny_steps = backward_chain(self.kb, deny_goal)
        if proved_deny:
            return self._build_result(drone, zone, deny_goal, deny_steps, authorized=False)

        proved_allow, allow_steps = backward_chain(self.kb, allow_goal)
        if proved_allow:
            return self._build_result(drone, zone, allow_goal, allow_steps, authorized=True)

        return InferenceResult(
            query_text=str(allow_goal),
            drone=drone, zone=zone,
            facts_considered=self._relevant_facts(zone, drone),
            rule_matched="(none)",
            substitution="-",
            proof_lines=["No rule could establish FlyOver or ¬FlyOver for this zone.",
                         "Closed-world default: unknown airspace is treated as non-authorized."],
            authorized=False,
            decision="DENIED (default - no rule authorizes entry)",
        )

    def _build_result(self, drone, zone, goal, steps, authorized) -> InferenceResult:
        rule_step = next((s for s in steps if s.kind == "rule"), None)
        lines = [s.text for s in steps]
        return InferenceResult(
            query_text=str(goal),
            drone=drone, zone=zone,
            facts_considered=self._relevant_facts(zone, drone),
            rule_matched=rule_step.rule.name if rule_step else "(fact)",
            substitution=(", ".join(f"{k}={v}" for k, v in rule_step.substitution.items())
                          if rule_step and rule_step.substitution else "-"),
            proof_lines=lines,
            authorized=authorized,
            decision="AUTHORIZED" if authorized else "DENIED",
        )

    def _relevant_facts(self, zone, drone):
        """Facts actually about this zone, plus the drone's registration -
        NOT every NoPermit(drone, *) fact (they all mention `drone`)."""
        return [f for f in self.kb.facts
                if zone in f.args or f == Atom(DRONE_PRED, (drone,))]

    # -- bulk reasoning ---------------------------------------------------

    def forward_map(self, drone: str) -> dict:
        """Forward-chain the whole KB and return {zone: 'AUTHORIZED'|'DENIED'}
        for every known zone, for the given drone."""
        facts, _trace = forward_chain(self.kb)
        result = {}
        for zone in self.zone_types:
            denied = Atom(FLY_OVER, (drone, zone), positive=False) in facts
            allowed = Atom(FLY_OVER, (drone, zone), positive=True) in facts
            if denied:
                result[zone] = "DENIED"
            elif allowed:
                result[zone] = "AUTHORIZED"
            else:
                result[zone] = "DENIED"
        return result

    def all_facts_sorted(self):
        return sorted(self.kb.facts, key=lambda a: (a.predicate, a.args))
