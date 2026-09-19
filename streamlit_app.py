"""
Green Transition Check — World Bank Data API
Group assignment: From Data to App.

Audience : people arguing about the green transition in Denmark — students,
           journalists, anyone who has heard "Denmark is a green frontrunner"
           and wants to check it against comparable countries.
Question : Is Denmark actually cutting CO2 faster than comparable countries,
           or does it just have a head start?
Data     : World Bank Indicators API (free, no key) — api.worldbank.org/v2
"""

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

API_ROOT = "https://api.worldbank.org/v2"
TIMEOUT = 15

# --- indicators the user can switch between -------------------------------
INDICATORS = {
    "CO2 emissions per capita": {
        "code": "EN.GHG.CO2.PC.CE.AR5",
        "unit": "tonnes CO2e per person",
        "good_direction": "down",
        "blurb": "Fossil CO2 emissions (excluding land use), divided by population.",
    },
    "Renewable energy share": {
        "code": "EG.FEC.RNEW.ZS",
        "unit": "% of final energy use",
        "good_direction": "up",
        "blurb": "Share of all energy consumed — heat, transport, electricity — that is renewable.",
    },
    "Renewable electricity output": {
        "code": "EG.ELC.RNEW.ZS",
        "unit": "% of electricity produced",
        "good_direction": "up",
        "blurb": "Share of electricity generation coming from renewable sources.",
    },
    "GDP per capita": {
        "code": "NY.GDP.PCAP.KD",
        "unit": "constant 2015 US$",
        "good_direction": "up",
        "blurb": "Economic output per person — useful to check whether falling emissions came with a shrinking economy.",
    },
}

DEFAULT_COUNTRIES = ["DNK", "SWE", "DEU", "NLD"]

# Validated categorical palette, fixed order (light / dark steps).
PALETTE = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"],
}
INK = {
    "light": {"primary": "#0b0b0b", "secondary": "#52514e", "grid": "#e3e2dd"},
    "dark": {"primary": "#ffffff", "secondary": "#c3c2b7", "grid": "#33322f"},
}
MAX_SERIES = len(PALETTE["light"])


# --------------------------------------------------------------------------
# Data layer — every call goes through here, so every failure looks the same
# --------------------------------------------------------------------------
def fetch(path, params):
    """Return (payload, error). Exactly one of the two is None."""
    params = {"format": "json", "per_page": 20000, **params}
    try:
        r = requests.get(f"{API_ROOT}/{path}", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        payload = r.json()
    except requests.exceptions.Timeout:
        return None, f"The World Bank API did not answer within {TIMEOUT} seconds."
    except requests.exceptions.ConnectionError:
        return None, "Could not reach the World Bank API — check your internet connection."
    except requests.exceptions.HTTPError as e:
        return None, f"The World Bank API returned an error ({e.response.status_code})."
    except ValueError:
        return None, "The World Bank API returned something that was not valid JSON."
    except requests.exceptions.RequestException as e:
        return None, f"Request to the World Bank API failed: {e}"

    # The API answers errors with HTTP 200 and a {"message": [...]} body.
    if isinstance(payload, dict) or (payload and isinstance(payload[0], dict) and "message" in payload[0]):
        head = payload[0] if isinstance(payload, list) else payload
        msg = head.get("message", [{}])[0].get("value", "unknown error")
        return None, f"The World Bank API rejected the request: {msg}"
    if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
        return None, "The World Bank API returned no rows for this request."
    return payload[1], None


@st.cache_data(ttl=3600, show_spinner=False)
def load_countries():
    rows, error = fetch("country", {})
    if error:
        return None, error
    countries = {
        r["id"]: r["name"]
        for r in rows
        if r["region"]["value"] != "Aggregates"  # drop "World", "Euro area", ...
    }
    return dict(sorted(countries.items(), key=lambda kv: kv[1])), None


@st.cache_data(ttl=3600, show_spinner=False)
def load_indicator(code, iso3_codes):
    rows, error = fetch(f"country/{';'.join(iso3_codes)}/indicator/{code}", {"date": "1990:2025"})
    if error:
        return None, error
    df = pd.DataFrame(
        [
            {"iso3": r["countryiso3code"], "country": r["country"]["value"],
             "year": int(r["date"]), "value": r["value"]}
            for r in rows
            if r["value"] is not None
        ]
    )
    if df.empty:
        return None, "The API answered, but has no observations for this indicator and these countries."
    return df.sort_values(["country", "year"]), None


# --------------------------------------------------------------------------
# Colour: one slot per country, held in session_state, so removing a country
# never repaints the ones that stay.
# --------------------------------------------------------------------------
def colour_for(iso3, mode):
    slots = st.session_state.setdefault("slots", {})
    if iso3 not in slots:
        taken = set(slots.values())
        slots[iso3] = next((i for i in range(MAX_SERIES) if i not in taken), 0)
    return PALETTE[mode][slots[iso3]]


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------
st.set_page_config(page_title="Green Transition Check", page_icon="🌍", layout="wide")

try:
    MODE = "dark" if st.context.theme.type == "dark" else "light"
except Exception:
    MODE = "light"
ink = INK[MODE]

st.title("🌍 Green Transition Check")
st.caption(
    "Denmark is routinely called a green frontrunner. This app checks that claim against "
    "comparable countries, using live data from the World Bank Indicators API."
)

countries, error = load_countries()
if error:
    st.error(f"**Could not load the country list.** {error}")
    st.button("Try again", on_click=st.cache_data.clear)
    st.stop()

with st.sidebar:
    st.header("Controls")
    indicator_name = st.selectbox("Indicator", list(INDICATORS), index=0)
    meta = INDICATORS[indicator_name]

    picked = st.multiselect(
        "Countries (max 6)",
        options=list(countries),
        default=[c for c in DEFAULT_COUNTRIES if c in countries],
        format_func=lambda iso3: countries[iso3],
        max_selections=MAX_SERIES,
    )
    st.caption("Add or remove countries to change every number on the page.")

if not picked:
    st.info("Pick at least one country in the sidebar to start.")
    st.stop()

# release colour slots of de-selected countries
st.session_state["slots"] = {k: v for k, v in st.session_state.get("slots", {}).items() if k in picked}

with st.spinner("Fetching data from the World Bank…"):
    df, error = load_indicator(meta["code"], picked)

if error:
    st.error(f"**No data to show.** {error}")
    st.caption("This is the API's answer, not a bug in the app — try another indicator, other countries, or again in a moment.")
    st.button("Try again", on_click=st.cache_data.clear)
    st.stop()

years = sorted(df["year"].unique())
with st.sidebar:
    start, end = st.select_slider(
        "Period",
        options=years,
        value=(years[0], years[-1]),
    )

view = df[df["year"].between(start, end)]
if view.empty or start == end:
    st.warning("That period is too short — widen it in the sidebar.")
    st.stop()

# --- the numbers the story rests on ---------------------------------------
change = (
    view.sort_values("year")
    .groupby(["iso3", "country"])["value"]
    .agg(first="first", last="last")
    .reset_index()
)
change["delta"] = change["last"] - change["first"]
change["pct"] = change["delta"] / change["first"] * 100
change = change.sort_values("pct", ascending=(meta["good_direction"] == "down"))

st.subheader(f"{indicator_name}, {start}–{end}")

cols = st.columns(len(change))
for col, row in zip(cols, change.itertuples()):
    col.metric(row.country, f"{row.last:,.1f}", f"{row.pct:+.1f}% since {start}")
st.caption(f"Latest value, {meta['unit']}. Arrow shows the change over the selected period.")

# --- chart 1: the path over time ------------------------------------------
fig = go.Figure()
for iso3, g in view.groupby("iso3"):
    g = g.sort_values("year")
    fig.add_trace(
        go.Scatter(
            x=g["year"], y=g["value"], name=g["country"].iloc[0], mode="lines",
            line=dict(color=colour_for(iso3, MODE), width=2),
            hovertemplate="%{fullData.name}<br>%{x}: %{y:,.1f}<extra></extra>",
        )
    )
    if len(picked) <= 4:  # direct labels stay readable up to four series
        last = g.iloc[-1]
        fig.add_annotation(
            x=last["year"], y=last["value"], text=f" {last['country']}",
            xanchor="left", showarrow=False, font=dict(color=ink["primary"], size=12),
        )

fig.update_layout(
    height=420,
    hovermode="x unified",
    margin=dict(t=10, r=110 if len(picked) <= 4 else 10, b=0, l=0),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=ink["secondary"]),
    legend=dict(orientation="h", y=-0.15, title_text=""),
    xaxis=dict(showgrid=False, linecolor=ink["grid"], title=""),
    yaxis=dict(gridcolor=ink["grid"], zeroline=False, title=meta["unit"]),
)
st.plotly_chart(fig, width="stretch")

# --- chart 2: speed, not level --------------------------------------------
st.markdown("**Change over the period** — the line chart shows the level, this shows the speed.")
bar = go.Figure(
    go.Bar(
        x=change["pct"],
        y=change["country"],
        orientation="h",
        marker=dict(
            color=[colour_for(i, MODE) for i in change["iso3"]],
            line=dict(color=ink["grid"], width=2),  # 2px surface gap between bars
        ),
        text=[f"{p:+.1f}%" for p in change["pct"]],
        textposition="outside",
        textfont=dict(color=ink["primary"]),
        hovertemplate="%{y}: %{x:+.1f}%<extra></extra>",
    )
)
bar.update_layout(
    height=60 * len(change) + 80,
    margin=dict(t=10, r=60, b=0, l=0),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=ink["secondary"]),
    xaxis=dict(gridcolor=ink["grid"], zeroline=True, zerolinecolor=ink["secondary"],
               title=f"% change, {start} to {end}"),
    yaxis=dict(title="", showgrid=False),
)
st.plotly_chart(bar, width="stretch")

# --- the story, in words --------------------------------------------------
lead, trail = change.iloc[0], change.iloc[-1]
direction = "fallen" if lead.delta < 0 else "risen"
st.markdown(
    f"""
### What the charts show
{meta['blurb']}

Between **{start}** and **{end}**, **{lead.country}** moved fastest in the
direction you want for *{indicator_name.lower()}*: it has {direction} by
**{abs(lead.pct):.1f}%**, from {lead.first:,.1f} to {lead.last:,.1f} {meta['unit']}.
**{trail.country}** moved least, at **{trail.pct:+.1f}%**.

The two charts answer different questions on purpose. The line chart shows the
**level** — who is best off today. The bar chart shows the **speed** — who is
changing fastest. A country can lead on one and trail on the other, and that gap
is usually where the interesting argument is: a head start is not the same as
momentum.
"""
)

with st.expander("One limitation of this data"):
    st.markdown(
        f"""
**Production, not consumption.** World Bank emission and energy figures are
measured inside a country's borders. Goods manufactured in China and consumed in
Denmark count as Chinese emissions, so a rich country that has moved its industry
abroad looks greener than its actual footprint. Biomass counts as renewable here
even when it is imported and burned.

Two more things worth saying out loud: the series is **not complete to today** —
the latest year available for this indicator is **{years[-1]}**, and some countries
lag further behind — and figures for recent years are revised after publication.
"""
    )

with st.expander("See the underlying data"):
    st.dataframe(
        view.pivot(index="year", columns="country", values="value").round(2),
        width="stretch",
    )
    st.download_button(
        "Download as CSV",
        view.to_csv(index=False).encode("utf-8"),
        file_name=f"worldbank_{meta['code']}_{start}_{end}.csv",
        mime="text/csv",
    )

st.caption(
    f"Source: World Bank Indicators API — indicator `{meta['code']}`. "
    "Free and open, no API key required."
)
