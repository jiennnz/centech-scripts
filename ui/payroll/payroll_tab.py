import streamlit as st
from datetime import date, timedelta

from modules.s3_sync import sync_s3_data


def render_payroll_tab():
    st.header("Payroll Pipeline")

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", value=date.today() - timedelta(days=14), key="payroll_start")
    with col2:
        end_date = st.date_input("End Date", value=date.today(), key="payroll_end")

    run_type = st.selectbox("Run Type", ["Full", "Semi"], key="payroll_run_type")

    st.divider()

    if st.button("Run Payroll Pipeline", key="payroll_run"):
        log_box = st.empty()
        logs = []

        def log(msg):
            logs.append(msg)
            log_box.code("\n".join(logs))

        # TODO: call run_payroll_pipeline() here once implemented
        log("🚧 Payroll pipeline not yet implemented.")