import streamlit as st
from datetime import date, timedelta

from modules.s3_sync import sync_s3_data


def render_data_tab():
    st.header("Data")
    st.write("Manually sync data from S3 for a given date range.")

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", value=date.today() - timedelta(days=14), key="data_start")
    with col2:
        end_date = st.date_input("End Date", value=date.today(), key="data_end")

    if st.button("Run S3 Sync", key="data_sync"):
        log_box = st.empty()
        logs = []

        def log(msg):
            logs.append(msg)
            log_box.code("\n".join(logs))

        success = sync_s3_data(
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            log_fn=log,
        )

        if success:
            st.success("Sync complete!")
        else:
            st.error("Sync completed with errors. Check logs above.")