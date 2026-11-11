"""Dice Roller: pick how many dice, press Roll, and see a bar chart of the totals.

Run it with:  streamlit run app.py
"""

import random

import altair as alt
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Dice Roller")


# ---------- Remembered between clicks ----------
def reset():
    """Clear every roll and start again at zero."""
    st.session_state.totals = {}      # total -> how many times it came up
    st.session_state.rolls = 0        # how many times we rolled
    st.session_state.last_faces = []  # the dice from the most recent roll
    st.session_state.lowest = 0       # fewest dice used in any roll (0 = none yet)
    st.session_state.highest = 0      # most dice used in any roll


if "totals" not in st.session_state:
    reset()


def roll_once(n):
    """Roll n dice one time and remember the result."""
    state = st.session_state
    faces = [random.randint(1, 6) for _ in range(n)]
    total = sum(faces)
    state.totals[total] = state.totals.get(total, 0) + 1
    state.rolls += 1
    state.last_faces = faces
    if state.lowest == 0 or n < state.lowest:
        state.lowest = n
    if n > state.highest:
        state.highest = n


def on_roll():
    roll_once(st.session_state.dice_count)


def on_roll_100():
    for _ in range(100):
        roll_once(st.session_state.dice_count)


# ---------- Page ----------
st.title("Dice Roller")
st.write(
    "Pick how many dice, press Roll, and watch the bars grow. "
    "Changing the number of dice keeps your old rolls. Press Reset to start over."
)

# Input 1: a dropdown for the number of dice.
dice_count = st.selectbox(
    "How many dice?",
    [1, 2, 3, 4],
    index=1,
    key="dice_count",
    format_func=lambda n: "1 die" if n == 1 else f"{n} dice",
)

# Input 2: three buttons.
col1, col2, col3 = st.columns(3)
col1.button("Roll", on_click=on_roll, type="primary", width="stretch")
col2.button("Roll 100 times", on_click=on_roll_100, width="stretch")
col3.button("Reset", on_click=reset, width="stretch")

state = st.session_state

# The last roll.
if state.last_faces:
    last_total = sum(state.last_faces)
    if len(state.last_faces) == 1:
        st.subheader(f"You rolled {last_total}")
    else:
        parts = " + ".join(str(face) for face in state.last_faces)
        st.subheader(f"You rolled {parts} = {last_total}")
else:
    last_total = None
    st.subheader("Press Roll to start.")

# ---------- Chart ----------
# The chart covers every dice count used so far, plus the one picked now.
fewest = dice_count
most = dice_count
if state.lowest > 0:
    fewest = min(fewest, state.lowest)
    most = max(most, state.highest)

rows = []
for total in range(fewest, 6 * most + 1):
    rows.append(
        {
            "Total": total,
            "Times": state.totals.get(total, 0),
            "IsLast": total == last_total,  # True only for the most recent roll
        }
    )
data = pd.DataFrame(rows)

chart = (
    alt.Chart(data)
    .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
    .encode(
        x=alt.X("Total:O", title="Total rolled", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("Times:Q", title="Times rolled", axis=alt.Axis(tickMinStep=1)),
        # Orange for the last roll, blue for everything else.
        color=alt.condition("datum.IsLast", alt.value("#eb6834"), alt.value("#2a78d6")),
        tooltip=["Total", "Times"],  # the hover box
    )
    .properties(height=300)
)
st.altair_chart(chart, width="stretch")

if state.rolls == 0:
    st.caption("No rolls yet.")
else:
    common = max(state.totals, key=state.totals.get)
    plural = "time" if state.rolls == 1 else "times"
    st.caption(
        f"Rolled {state.rolls} {plural}. "
        f"Most common total: {common} ({state.totals[common]} times). "
        "Orange bar: your last roll. Hover a bar to see its count."
    )

with st.expander("View as table"):
    st.dataframe(data[["Total", "Times"]], hide_index=True, width="stretch")
