import random
import re
import threading
import time

import pandas as pd
import plotly.express as px
import pycountry
import requests
import streamlit as st

st.set_page_config(
    page_title="Locational Search",
    layout="wide",
)

DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GEO_URL = "https://api.gdeltproject.org/api/v2/geo/geo"
CACHE_TIME = 900

COUNTRIES = sorted(
    country.name for country in pycountry.countries
)

BASE_QUERY = (
    "(election OR government OR parliament OR diplomacy "
    "OR conflict OR war OR economy OR trade OR climate "
    "OR earthquake OR wildfire OR technology OR health "
    "OR science OR migration OR energy OR security)"
)


@st.cache_resource
def request_state():
    return {
        "last_request": 0.0,
        "lock": threading.Lock(),
    }


def api_request(url, params):
    state = request_state()

    with state["lock"]:
        delay = 5 - (time.monotonic() - state["last_request"])

        if delay > 0:
            time.sleep(delay)

        response = requests.get(
            url,
            params=params,
            timeout=45,
            headers={"User-Agent": "LocationalSearch/1.0"},
        )

        state["last_request"] = time.monotonic()

    if response.status_code == 429:
        raise RuntimeError(
            "GDELT rate limit reached. Wait a moment and try again."
        )

    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "").lower()

    if "json" not in content_type and "geo+json" not in content_type:
        raise RuntimeError(
            "GDELT returned an unexpected response. Try again later."
        )

    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(
            "GDELT returned an invalid response."
        ) from exc


def country_filter(country):
    return re.sub(r"\s+", "", country.strip().lower())


@st.cache_data(ttl=CACHE_TIME, show_spinner=False)
def get_regions(country, timespan):
    query = (
        f"{BASE_QUERY} "
        f"locationcc:{country_filter(country)}"
    )

    params = {
        "query": query,
        "mode": "adm1",
        "format": "geojson",
        "timespan": timespan,
    }

    data = api_request(GEO_URL, params)

    features = data.get("features", [])
    results = []

    for feature in features:
        properties = feature.get("properties") or {}

        name = (
            properties.get("name")
            or properties.get("adm1_name")
            or properties.get("ADM1_NAME")
            or properties.get("label")
        )

        if not name:
            continue

        value = None

        for field in (
            "count",
            "mentions",
            "share",
            "percent",
            "percentage",
            "value",
            "score",
        ):
            try:
                raw_value = properties.get(field)

                if raw_value is not None:
                    value = float(raw_value)
                    break
            except (TypeError, ValueError):
                continue

        results.append({
            "Region": str(name),
            "GDELT value": value,
        })

    df = pd.DataFrame(results)

    if df.empty:
        return df

    df = df.drop_duplicates(
        subset=["Region"]
    ).reset_index(drop=True)

    if df["GDELT value"].notna().any():
        df = df.sort_values(
            "GDELT value",
            ascending=False,
            na_position="last",
        ).reset_index(drop=True)

    df.insert(0, "Rank", range(1, len(df) + 1))

    return df


@st.cache_data(ttl=CACHE_TIME, show_spinner=False)
def get_article_volume(search_query, timespan):
    params = {
        "query": search_query,
        "mode": "TimelineVolRaw",
        "format": "json",
        "timespan": timespan,
    }

    data = api_request(DOC_URL, params)

    total = 0
    found = False

    for series in data.get("timeline", []):
        for point in series.get("data", []):
            value = point.get("value")

            if value is not None:
                try:
                    total += int(float(value))
                    found = True
                except (TypeError, ValueError):
                    pass

    return total if found else None


@st.cache_data(ttl=CACHE_TIME, show_spinner=False)
def get_articles(search_query, timespan):
    params = {
        "query": search_query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": 100,
        "timespan": timespan,
        "sort": "DateDesc",
    }

    data = api_request(DOC_URL, params)
    articles = data.get("articles", [])

    if not articles:
        return pd.DataFrame(
            columns=["Headline", "Publisher", "Date", "URL"]
        )

    df = pd.DataFrame(articles)

    for column in ("title", "domain", "seendate", "url"):
        if column not in df.columns:
            df[column] = ""

    df = df.rename(columns={
        "title": "Headline",
        "domain": "Publisher",
        "seendate": "Date",
        "url": "URL",
    })

    df = df[
        ["Headline", "Publisher", "Date", "URL"]
    ].copy()

    df = df.fillna("")
    df = df[df["Headline"].astype(str).str.strip() != ""]

    return df.drop_duplicates(
        subset=["URL", "Headline"]
    )


st.markdown(
    """
    <style>
    .block-container {
        max-width: 1450px;
        padding-top: 1.6rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Locational Search")

st.write(
    "Explore how countries and their regions appear in recent "
    "international news coverage."
)


with st.sidebar:
    st.header("Search settings")

    if st.button("Choose random country", use_container_width=True):
        st.session_state["country_choice"] = random.choice(COUNTRIES)
        st.session_state.pop("region_choice", None)
        st.rerun()

    default_country = st.session_state.get(
        "country_choice",
        "Mongolia",
    )

    if default_country not in COUNTRIES:
        default_country = "Mongolia"

    country = st.selectbox(
        "Country",
        COUNTRIES,
        index=COUNTRIES.index(default_country),
        key="country_choice",
    )

    period_label = st.selectbox(
        "News coverage period",
        ["Last 24 hours", "Last 3 days", "Last 7 days"],
        index=2,
    )

    period = {
        "Last 24 hours": "1d",
        "Last 3 days": "3d",
        "Last 7 days": "7d",
    }[period_label]


st.subheader(f"Country overview: {country}")

st.caption(period_label)

region_error = None
volume_error = None

with st.spinner("Loading country data..."):
    try:
        regions = get_regions(country, period)
    except (requests.RequestException, RuntimeError) as exc:
        regions = pd.DataFrame()
        region_error = str(exc)

    try:
        country_volume = get_article_volume(
            f'"{country}"',
            period,
        )
    except (requests.RequestException, RuntimeError) as exc:
        country_volume = None
        volume_error = str(exc)


col1, col2, col3 = st.columns(3)

col1.metric("Country", country)

col2.metric(
    "Matching news articles",
    f"{country_volume:,}" if country_volume is not None else "Unavailable",
)

col3.metric(
    "Regions returned",
    f"{len(regions):,}" if not regions.empty else "Unavailable",
)

st.caption(
    "Article volume measures matching news coverage. "
    "It does not measure how many people searched online."
)


if region_error:
    st.error(region_error)

elif regions.empty:
    st.info(
        "No regional results were returned. "
        "Try another country or a longer time period."
    )

else:
    st.subheader("Regional results")

    if "show_all_regions" not in st.session_state:
        st.session_state["show_all_regions"] = False

    if st.button(
        "Show all returned regions"
        if not st.session_state["show_all_regions"]
        else "Show top five only"
    ):
        st.session_state["show_all_regions"] = (
            not st.session_state["show_all_regions"]
        )
        st.rerun()

    shown_regions = (
        regions
        if st.session_state["show_all_regions"]
        else regions.head(5)
    )

    display_df = shown_regions.copy()

    display_df["GDELT value"] = display_df[
        "GDELT value"
    ].map(
        lambda value: (
            round(value, 2)
            if pd.notna(value)
            else "Unavailable"
        )
    )

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
    )

    chart_data = regions.dropna(
        subset=["GDELT value"]
    ).head(15)

    if not chart_data.empty:
        fig = px.bar(
            chart_data.sort_values("GDELT value"),
            x="GDELT value",
            y="Region",
            orientation="h",
            title="Regional coverage ranking",
        )

        st.plotly_chart(
            fig,
            use_container_width=True,
        )

    st.subheader("Search within a region")

    region_names = regions["Region"].tolist()

    if st.button("Choose random region"):
        st.session_state["region_choice"] = random.choice(
            region_names
        )
        st.rerun()

    default_region = st.session_state.get(
        "region_choice",
        region_names[0],
    )

    if default_region not in region_names:
        default_region = region_names[0]

    selected_region = st.selectbox(
        "Select a state, province or region",
        region_names,
        index=region_names.index(default_region),
        key="region_choice",
    )

    st.markdown(f"#### {selected_region}")

    region_query = (
        f'"{selected_region}" "{country}"'
    )

    try:
        with st.spinner("Searching regional news coverage..."):
            region_volume = get_article_volume(
                region_query,
                period,
            )

        st.metric(
            "Matching news articles",
            (
                f"{region_volume:,}"
                if region_volume is not None
                else "Unavailable"
            ),
        )

    except (requests.RequestException, RuntimeError) as exc:
        st.warning(str(exc))

    try:
        with st.spinner("Loading example headlines..."):
            articles = get_articles(
                region_query,
                period,
            )

        if articles.empty:
            st.info("No matching headlines were returned.")

        else:
            st.markdown("#### Example headlines")

            for _, article in articles.head(10).iterrows():
                headline = article["Headline"]
                publisher = article["Publisher"]
                url = article["URL"]

                if url:
                    st.markdown(
                        f"- [{headline}]({url}) — {publisher}"
                    )
                else:
                    st.markdown(
                        f"- {headline} — {publisher}"
                    )

    except (requests.RequestException, RuntimeError) as exc:
        st.warning(str(exc))


if volume_error:
    st.warning(volume_error)


st.divider()

st.subheader("Topic search")

topic = st.text_input(
    "Enter a topic or phrase",
    placeholder="Example: climate change",
)

if st.button(
    "Search topic",
    type="primary",
    disabled=not topic.strip(),
):
    try:
        with st.spinner("Searching news coverage..."):
            topic_volume = get_article_volume(
                f'"{topic.strip()}"',
                period,
            )

        st.metric(
            "Matching news articles",
            (
                f"{topic_volume:,}"
                if topic_volume is not None
                else "Unavailable"
            ),
        )

    except (requests.RequestException, RuntimeError) as exc:
        st.error(str(exc))


st.caption(
    "Data source: GDELT Project DOC 2.0 and GEO 2.0 APIs."
)
