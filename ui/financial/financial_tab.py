import streamlit as st
from datetime import date, timedelta


def render_financial_tab():
    st.header("Financial Pipeline")

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", value=date.today() - timedelta(days=14), key="financial_start")
    with col2:
        end_date = st.date_input("End Date", value=date.today(), key="financial_end")

    run_type = st.selectbox("Run Type", ["Full", "Semi"], key="financial_run_type")

    st.divider()

    if st.button("Run Financial Pipeline", key="financial_run"):
        log_box = st.empty()
        logs = []

        def log(msg):
            logs.append(msg)
            log_box.code("\n".join(logs))

        # TODO: call run_financial_pipeline() here once implemented
        log("🚧 Financial pipeline not yet implemented.")