from __future__ import annotations

import streamlit as st


st.set_page_config(page_title="Weatherman · Research offline", page_icon="🧪")
st.title("Airport Research is offline")
st.info(
    "The broad Airport Research workspace was removed from the production data path "
    "in v10.7.8 to protect Streamlit memory. The six trading airports remain available "
    "in Trading Desk, including their compact Forecast Ladder History. Historical replay "
    "and broad research continue only in isolated research workflows."
)
st.page_link("app.py", label="Return to Trading Desk")
