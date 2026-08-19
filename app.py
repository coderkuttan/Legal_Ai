"""
Phase 5 - Streamlit UI
======================
The interactive "mission control" console. Wires together the grid world,
the FOL knowledge base and the drone mission controller into a single
dashboard: live 2D map, explainable inference panel, event log, permit /
NOTAM controls, manual override, and a knowledge-base explorer.

Run with:  streamlit run app.py
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from airspace_kb import AirspaceKB, RULES
from drone_agent import (
    Mission, DRONE_ID,
    PHASE_PLANNING, PHASE_TO_TARGET, PHASE_CAPTURING, PHASE_RETURNING,
    PHASE_COMPLETE, PHASE_FAILED, PHASE_INTERCEPTED,
)
from grid_world import build_default_grid, COLS, ROWS, zone_coords, ZONE_COLORS, TEMP_RESTRICTED_COLOR

st.set_page_config(page_title="SENTINEL - FOL Airspace Agent", page_icon="🛰️", layout="wide")

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

st.markdown("""
<style>
.stApp { background: radial-gradient(circle at 20% 0%, #101826 0%, #070b12 55%, #050709 100%); }
h1, h2, h3, h4, p, span, label, div { color: #dbe4ee; }
section[data-testid="stSidebar"] { background: #0a0f18; border-right: 1px solid #1c2836; }

.hero { display:flex; justify-content:space-between; align-items:center;
        padding: 14px 22px; border-radius: 14px; margin-bottom: 14px;
        background: linear-gradient(135deg, #0e1826 0%, #0a2233 100%);
        border: 1px solid #1e3a52; }
.hero h1 { margin:0; font-size: 1.5rem; letter-spacing: 1px; color:#7fd6ff; }
.hero p { margin:0; color:#7c93a8; font-size: 0.85rem; }

.badge { display:inline-block; padding: 5px 14px; border-radius: 999px;
         font-weight:700; font-size: 0.8rem; letter-spacing: 0.5px; color:#04141c; }

.card { background:#0d1420; border:1px solid #1c2836; border-radius:12px;
        padding:14px 16px; margin-bottom:10px; }
.card h4 { margin:0 0 8px 0; color:#7fd6ff; font-size:0.95rem; }

.kv { font-family: 'Courier New', monospace; font-size:0.82rem; color:#b7c7d6; margin:2px 0; }
.kv b { color:#7fd6ff; }

.proof-line { font-family:'Courier New', monospace; font-size:0.8rem; color:#9fe3a8;
              border-left:3px solid #2ecc71; padding:2px 8px; margin:3px 0; background:rgba(46,204,113,0.06); }

.log-wrap { max-height: 480px; overflow-y:auto; padding-right:6px; }
.log-row { font-family:'Courier New', monospace; font-size:0.78rem; padding:5px 10px;
           margin:3px 0; border-radius:6px; border-left:4px solid #333; background:#0c131e; }
.log-INFO{border-left-color:#5b7386;} .log-QUERY{border-left-color:#9b59b6;}
.log-PAUSE{border-left-color:#f1c40f;} .log-MOVE{border-left-color:#2ecc71;}
.log-DENIED{border-left-color:#e74c3c;} .log-REROUTE{border-left-color:#3498db;}
.log-CAPTURE{border-left-color:#1abc9c;} .log-OVERRIDE{border-left-color:#e67e22;}
.log-INTERCEPTED{border-left-color:#c0392b; background:#1a0d0d;}
.log-COMPLETE{border-left-color:#2ecc71; background:#0d1a10;}
.log-FAILED{border-left-color:#c0392b; background:#1a0d0d;}
</style>
""", unsafe_allow_html=True)

PHASE_COLOR = {
    PHASE_PLANNING: "#3498db", PHASE_TO_TARGET: "#2ecc71", PHASE_CAPTURING: "#1abc9c",
    PHASE_RETURNING: "#f1c40f", PHASE_COMPLETE: "#2ecc71", PHASE_FAILED: "#e74c3c",
    PHASE_INTERCEPTED: "#c0392b",
}
LOG_ICON = {
    "INFO": "ℹ️", "QUERY": "🔎", "PAUSE": "⏸️", "MOVE": "➡️", "DENIED": "🚫",
    "REROUTE": "🔄", "CAPTURE": "📸", "OVERRIDE": "⚠️", "INTERCEPTED": "🛑",
    "COMPLETE": "✅", "FAILED": "❌",
}
TYPE_LABEL = {"safe": "Safe Zone", "controlled": "Controlled Zone",
              "restricted": "Restricted (Defense)", "corridor": "Flight Corridor"}

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def fresh_kb():
    return AirspaceKB(build_default_grid())


if "kb" not in st.session_state:
    st.session_state.kb = fresh_kb()
    st.session_state.mission = Mission(st.session_state.kb, "A1", "H8", "A1")
    st.session_state.manual_inference = None

kb: AirspaceKB = st.session_state.kb
mission: Mission = st.session_state.mission
all_zones = sorted(kb.zone_types.keys())
gated_zones = sorted(z for z, t in kb.zone_types.items() if t in ("restricted", "controlled"))

# ---------------------------------------------------------------------------
# Sidebar - controls
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### 🛰️ Mission Setup")
    c1, c2 = st.columns(2)
    start_zone = c1.selectbox("Start / Base", all_zones, index=all_zones.index("A1"))
    target_zone = c2.selectbox("Surveillance Target", all_zones, index=all_zones.index("H8"))
    if st.button("🚀 Launch New Mission", use_container_width=True):
        st.session_state.mission = Mission(kb, start_zone, target_zone, start_zone)
        st.rerun()

    st.markdown("### 🪪 Drone Permits")
    st.caption("Grants HasPermit(Drone1, x) - required for Restricted / Controlled zones.")
    granted = st.multiselect(
        "Zones with an active flight permit",
        gated_zones,
        default=[z for z in gated_zones if kb.has_permit(DRONE_ID, z)],
    )
    for z in gated_zones:
        if z in granted:
            kb.grant_permit(DRONE_ID, z)
        else:
            kb.revoke_permit(DRONE_ID, z)

    st.markdown("### 📡 Temporary Restrictions (NOTAM)")
    st.caption("Dynamically asserts TemporaryRestricted(x). Overrides any permit.")
    active_temp = st.multiselect(
        "Zones under an active NOTAM", all_zones, default=sorted(kb.temp_restricted),
    )
    for z in all_zones:
        if z in active_temp:
            kb.declare_temp_restriction(z)
        else:
            kb.lift_temp_restriction(z)

    st.markdown("### ⚠️ Manual Override")
    override_next = st.checkbox("Force entry on next step even if FOL denies it")
    st.caption("Simulates an unauthorized override → triggers interception + mission failure.")

    st.markdown("### ▶️ Simulation Controls")
    cs1, cs2 = st.columns(2)
    do_step = cs1.button("⏭ Step", use_container_width=True, disabled=mission.is_finished())
    do_run = cs2.button("⏩ Run to End", use_container_width=True, disabled=mission.is_finished())
    if st.button("♻️ Reset Everything (new KB)", use_container_width=True):
        st.session_state.kb = fresh_kb()
        st.session_state.mission = Mission(st.session_state.kb, "A1", "H8", "A1")
        st.session_state.manual_inference = None
        st.rerun()

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown(f"""
<div class="hero">
  <div>
    <h1>🛰️ SENTINEL - National Security Drone Surveillance Agent</h1>
    <p>First-Order Logic airspace-compliance reasoning · forward &amp; backward chaining · explainable decisions</p>
  </div>
  <div><span class="badge" style="background:{PHASE_COLOR[mission.phase]}">{mission.phase}</span></div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Simulation actions (mutate mission BEFORE rendering)
# ---------------------------------------------------------------------------

grid_ph = None  # placeholders created below, referenced inside animate loop


def build_grid_figure(kb: AirspaceKB, mission: Mission) -> go.Figure:
    legal_map = kb.forward_map(DRONE_ID)
    fig = go.Figure()
    by_type = {"safe": [], "controlled": [], "restricted": [], "corridor": []}
    for name, ztype in kb.zone_types.items():
        col, row = zone_coords(name)
        by_type[ztype].append((name, col, row))

    for ztype, cells in by_type.items():
        if not cells:
            continue
        xs = [c[1] for c in cells]
        ys = [c[2] for c in cells]
        names = [c[0] for c in cells]
        opacities = [1.0 if legal_map[c[0]] == "AUTHORIZED" else 0.32 for c in cells]
        line_colors = [TEMP_RESTRICTED_COLOR if c[0] in kb.temp_restricted else "rgba(255,255,255,0.25)" for c in cells]
        line_widths = [4 if c[0] in kb.temp_restricted else 1 for c in cells]
        hover = [
            f"<b>{c[0]}</b><br>Type: {TYPE_LABEL[ztype]}<br>Status: {legal_map[c[0]]}"
            + ("<br>⚠ NOTAM active" if c[0] in kb.temp_restricted else "")
            for c in cells
        ]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers+text",
            marker=dict(symbol="square", size=40, color=ZONE_COLORS[ztype],
                        opacity=opacities, line=dict(color=line_colors, width=line_widths)),
            text=names, textposition="middle center", textfont=dict(size=9, color="rgba(0,0,0,0.6)"),
            hovertext=hover, hoverinfo="text", name=TYPE_LABEL[ztype],
        ))

    if mission.path:
        xs = [zone_coords(z)[0] for z in mission.path]
        ys = [zone_coords(z)[1] for z in mission.path]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines",
                                  line=dict(color="rgba(0,229,255,0.55)", width=3, dash="dot"),
                                  hoverinfo="skip", showlegend=False))

    def marker(name, symbol, color, label):
        col, row = zone_coords(name)
        fig.add_trace(go.Scatter(
            x=[col], y=[row], mode="markers+text",
            marker=dict(symbol=symbol, size=24, color=color, line=dict(color="white", width=2)),
            text=[label], textposition="bottom center", textfont=dict(size=10, color=color),
            hoverinfo="skip", showlegend=False,
        ))

    marker(mission.base, "square-x", "#ffffff", "BASE")
    marker(mission.target, "star", "#ffe066", "TARGET")
    marker(mission.position, "triangle-up", "#00e5ff", "DRONE")

    fig.update_layout(
        xaxis=dict(tickmode="array", tickvals=list(range(8)), ticktext=list(COLS),
                   showgrid=True, gridcolor="rgba(255,255,255,0.07)", zeroline=False, range=[-0.7, 7.7]),
        yaxis=dict(tickmode="array", tickvals=list(range(8)), ticktext=[str(r) for r in ROWS],
                   showgrid=True, gridcolor="rgba(255,255,255,0.07)", zeroline=False, range=[-0.7, 7.7]),
        plot_bgcolor="#0b1220", paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#dbe4ee"),
        height=600, margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", y=-0.08, font=dict(size=11)),
    )
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    return fig


def render_inference_card(container, result, title):
    if result is None:
        container.markdown(f'<div class="card"><h4>{title}</h4><p style="color:#5b7386">No query run yet.</p></div>',
                            unsafe_allow_html=True)
        return
    badge_color = "#2ecc71" if result.authorized else "#e74c3c"
    facts_html = "".join(f'<div class="kv">• {f}</div>' for f in result.facts_considered) or '<div class="kv">(none)</div>'
    proof_html = "".join(f'<div class="proof-line">{i+1}. {line}</div>' for i, line in enumerate(result.proof_lines))
    container.markdown(f"""
    <div class="card">
      <h4>{title}</h4>
      <div class="kv"><b>Query:</b> {result.query_text}</div>
      <div class="kv"><b>Rule matched:</b> {result.rule_matched} &nbsp; <b>Substitution:</b> {{{result.substitution}}}</div>
      <div class="kv" style="margin-top:6px;"><b>Facts considered:</b></div>
      {facts_html}
      <div class="kv" style="margin-top:6px;"><b>Proof trace:</b></div>
      {proof_html}
      <div style="margin-top:10px;"><span class="badge" style="background:{badge_color}">{result.decision}</span></div>
    </div>
    """, unsafe_allow_html=True)


def render_log(container, mission):
    rows = []
    for e in reversed(mission.log[-200:]):
        icon = LOG_ICON.get(e.kind, "•")
        rows.append(f'<div class="log-row log-{e.kind}">[{e.step:03d}] {icon} <b>{e.kind}</b> — {e.message}</div>')
    container.markdown(f'<div class="card"><h4>📜 Mission Event &amp; Inference Log</h4>'
                        f'<div class="log-wrap">{"".join(rows)}</div></div>', unsafe_allow_html=True)


def render_status(container, mission):
    container.markdown(f"""
    <div class="card">
      <h4>🧭 Mission Status</h4>
      <div class="kv"><b>Drone:</b> {mission.drone}</div>
      <div class="kv"><b>Phase:</b> {mission.phase}</div>
      <div class="kv"><b>Position:</b> {mission.position}</div>
      <div class="kv"><b>Target:</b> {mission.target} &nbsp; <b>Base:</b> {mission.base}</div>
      <div class="kv"><b>Planned leg:</b> {' → '.join(mission.path) if mission.path else '-'}</div>
      <div class="kv"><b>Steps executed:</b> {mission.step_count}</div>
    </div>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

col_map, col_side = st.columns([2, 1])
with col_map:
    grid_placeholder = st.empty()
with col_side:
    status_placeholder = st.empty()
    inference_placeholder = st.empty()

log_placeholder = st.empty()


def render_all():
    grid_placeholder.plotly_chart(build_grid_figure(kb, mission), use_container_width=True,
                                   key=f"grid_{mission.step_count}")
    render_status(status_placeholder, mission)
    render_inference_card(inference_placeholder, mission.last_inference, "🔎 Live FOL Query (last zone entry)")
    render_log(log_placeholder, mission)


if do_step:
    mission.step(override=override_next)
    render_all()
elif do_run:
    import time
    guard = 0
    while not mission.is_finished() and guard < 200:
        mission.step(override=override_next and guard == 0)
        render_all()
        time.sleep(0.45)
        guard += 1
else:
    render_all()

# ---------------------------------------------------------------------------
# Manual FOL query explorer
# ---------------------------------------------------------------------------

st.markdown("### 🧪 Manual FOL Query")
mc1, mc2 = st.columns([1, 3])
with mc1:
    query_zone = st.selectbox("Zone to query", all_zones, key="manual_zone")
    if st.button("Run FlyOver query"):
        st.session_state.manual_inference = kb.query_flyover(DRONE_ID, query_zone)
with mc2:
    render_inference_card(st, st.session_state.manual_inference, f"Query result: FlyOver({DRONE_ID}, {query_zone})")

# ---------------------------------------------------------------------------
# Knowledge base explorer
# ---------------------------------------------------------------------------

with st.expander("📚 Knowledge Base Explorer (rules, facts, forward-chained legal map)"):
    st.markdown("#### Compliance Rules")
    for rule in RULES:
        st.markdown(f'<div class="kv"><b>{rule.name}:</b> {rule}</div><div class="kv" style="color:#5b7386">{rule.description}</div>',
                     unsafe_allow_html=True)

    st.markdown("#### Current Facts")
    facts_df = pd.DataFrame(
        [{"Predicate": f.predicate, "Args": ", ".join(f.args), "Sign": "positive" if f.positive else "negated"}
         for f in kb.all_facts_sorted()]
    )
    st.dataframe(facts_df, use_container_width=True, height=240)

    st.markdown("#### Forward-Chained Legal Map (every zone, current facts)")
    legal_map = kb.forward_map(DRONE_ID)
    legal_df = pd.DataFrame(
        [{"Zone": z, "Type": TYPE_LABEL[kb.zone_types[z]], "Decision": legal_map[z],
          "NOTAM": "yes" if z in kb.temp_restricted else "-"}
         for z in all_zones]
    )
    st.dataframe(
        legal_df.style.map(lambda v: "color:#2ecc71" if v == "AUTHORIZED" else ("color:#e74c3c" if v == "DENIED" else ""),
                            subset=["Decision"]),
        use_container_width=True, height=300,
    )

st.caption("Track 3 - Legal Compliance Drone · Unit 4 First-Order Logic Agent · "
           "Forward & backward chaining over Horn-clause rules, no hardcoded if/else airspace logic.")
