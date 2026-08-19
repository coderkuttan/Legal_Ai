"""
Phase 1 - FOL Engine
====================
A small, general-purpose First-Order Logic engine: unification, substitution,
forward chaining and backward chaining over function-free definite clauses
whose conclusions may be positive or negated literals.

This is domain-agnostic. `airspace_kb.py` is what plugs the drone/airspace
predicates and rules into it. Nothing about "drones" or "zones" lives here.
"""

import re
from dataclasses import dataclass, field
from itertools import count

_var_counter = count()
_SUFFIX_RE = re.compile(r"_\d+$")


def _display_name(var: "Variable") -> str:
    """Strip the standardize-apart suffix (e.g. 'x_47' -> 'x') for display."""
    return _SUFFIX_RE.sub("", var.name)


@dataclass(frozen=True)
class Variable:
    """A universally-quantified FOL variable, e.g. Variable('x')."""
    name: str

    def __repr__(self):
        return f"?{self.name}"


@dataclass(frozen=True)
class Atom:
    """A predicate applied to terms, e.g. Restricted(x) or FlyOver(drone, x).

    `positive=False` represents a negated literal, i.e. ¬Predicate(args).
    """
    predicate: str
    args: tuple
    positive: bool = True

    def negate(self):
        return Atom(self.predicate, self.args, not self.positive)

    def __repr__(self):
        sign = "" if self.positive else "¬"
        args = ", ".join(str(a) for a in self.args)
        return f"{sign}{self.predicate}({args})"


@dataclass(frozen=True)
class Rule:
    """A Horn-style rule: premises (all positive atoms) -> conclusion."""
    name: str
    premises: tuple
    conclusion: Atom
    description: str = ""

    def __repr__(self):
        body = " ∧ ".join(str(p) for p in self.premises)
        return f"{self.name}: {body} → {self.conclusion}"

    def renamed(self):
        """Return a copy with fresh variable names (standardize apart)."""
        suffix = next(_var_counter)
        mapping = {}

        def ren_term(t):
            if isinstance(t, Variable):
                if t.name not in mapping:
                    mapping[t.name] = Variable(f"{t.name}_{suffix}")
                return mapping[t.name]
            return t

        def ren_atom(a):
            return Atom(a.predicate, tuple(ren_term(t) for t in a.args), a.positive)

        return Rule(
            self.name,
            tuple(ren_atom(p) for p in self.premises),
            ren_atom(self.conclusion),
            self.description,
        )


# ---------------------------------------------------------------------------
# Unification
# ---------------------------------------------------------------------------

def unify_term(x, y, theta):
    if theta is None:
        return None
    x = theta.get(x, x) if isinstance(x, Variable) else x
    y = theta.get(y, y) if isinstance(y, Variable) else y
    if x == y:
        return theta
    if isinstance(x, Variable):
        new_theta = dict(theta)
        new_theta[x] = y
        return new_theta
    if isinstance(y, Variable):
        new_theta = dict(theta)
        new_theta[y] = x
        return new_theta
    return None


def unify(a: Atom, b: Atom, theta=None):
    """Unify two atoms. Returns a substitution dict, or None if they cannot unify."""
    if theta is None:
        theta = {}
    if a.predicate != b.predicate or a.positive != b.positive or len(a.args) != len(b.args):
        return None
    for x, y in zip(a.args, b.args):
        theta = unify_term(x, y, theta)
        if theta is None:
            return None
    return theta


def subst(theta, atom: Atom) -> Atom:
    def sub_term(t):
        seen = set()
        while isinstance(t, Variable) and t in theta and t.name not in seen:
            seen.add(t.name)
            t = theta[t]
        return t

    return Atom(atom.predicate, tuple(sub_term(a) for a in atom.args), atom.positive)


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------

class KnowledgeBase:
    def __init__(self):
        self.facts: list[Atom] = []
        self.rules: list[Rule] = []

    def tell_fact(self, atom: Atom):
        if atom not in self.facts:
            self.facts.append(atom)

    def retract_fact(self, atom: Atom):
        if atom in self.facts:
            self.facts.remove(atom)

    def tell_rule(self, rule: Rule):
        self.rules.append(rule)

    def facts_matching(self, predicate=None):
        if predicate is None:
            return list(self.facts)
        return [f for f in self.facts if f.predicate == predicate]


# ---------------------------------------------------------------------------
# Forward chaining
# ---------------------------------------------------------------------------

@dataclass
class Derivation:
    rule: Rule
    substitution: dict
    conclusion: Atom


def _atom_in(atom, facts):
    return any(f == atom for f in facts)


def _extend_with_premises(premises, facts, theta):
    """Yield all substitutions that satisfy every premise against `facts`."""
    if not premises:
        yield theta
        return
    first, rest = premises[0], premises[1:]
    for fact in facts:
        theta2 = unify(subst(theta, first), fact, dict(theta))
        if theta2 is not None:
            yield from _extend_with_premises(rest, facts, theta2)


def forward_chain(kb: KnowledgeBase):
    """Derive every fact entailed by kb.facts + kb.rules (fixpoint).

    Returns (all_facts, trace) where trace is an ordered list of Derivation
    objects describing exactly which rule fired, with what substitution,
    to produce which new fact.
    """
    facts = list(kb.facts)
    trace: list[Derivation] = []
    changed = True
    while changed:
        changed = False
        for rule in kb.rules:
            r = rule.renamed()
            for theta in _extend_with_premises(list(r.premises), facts, {}):
                new_atom = subst(theta, r.conclusion)
                if not any(v for v in new_atom.args if isinstance(v, Variable)):
                    if not _atom_in(new_atom, facts):
                        facts.append(new_atom)
                        trace.append(Derivation(rule, theta, new_atom))
                        changed = True
    return facts, trace


# ---------------------------------------------------------------------------
# Backward chaining
# ---------------------------------------------------------------------------

@dataclass
class ProofStep:
    kind: str          # "fact" or "rule"
    text: str
    rule: Rule = None
    substitution: dict = None


def backward_chain(kb: KnowledgeBase, goal: Atom):
    """Try to prove `goal` against kb. Returns (proved: bool, steps: list[ProofStep]).

    Only the first successful proof is reported (sufficient for an
    authorization query where we just need one valid justification).
    """
    steps: list[ProofStep] = []
    theta = _bc_prove(kb, goal, {}, steps, depth=0)
    return theta is not None, steps


def _bc_prove(kb: KnowledgeBase, goal: Atom, theta, steps, depth, _budget=None):
    if depth > 12:
        return None

    grounded_goal = subst(theta, goal)

    # 1. Try to match a known fact directly.
    for fact in kb.facts:
        theta2 = unify(fact, grounded_goal, dict(theta))
        if theta2 is not None:
            steps.append(ProofStep(kind="fact", text=f"Fact matched: {fact}"))
            return theta2

    # 2. Try every rule whose conclusion has the same predicate/sign.
    for rule in kb.rules:
        r = rule.renamed()
        theta2 = unify(r.conclusion, grounded_goal, dict(theta))
        if theta2 is None:
            continue
        sub_steps = []
        ok = True
        for premise in r.premises:
            theta2 = _bc_prove(kb, premise, theta2, sub_steps, depth + 1)
            if theta2 is None:
                ok = False
                break
        if ok:
            binding = {_display_name(k): v for k, v in theta2.items() if k not in theta}
            steps.append(ProofStep(
                kind="rule",
                text=f"Rule {rule.name} matched ({rule}) with substitution "
                     f"{{{', '.join(f'{k}={v}' for k, v in binding.items())}}}",
                rule=rule,
                substitution=binding,
            ))
            steps.extend(sub_steps)
            return theta2

    return None
