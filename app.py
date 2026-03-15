import streamlit as st

from ui.payroll.payroll_tab import render_payroll_tab
from ui.financial.financial_tab import render_financial_tab
from ui.data_sync.data_sync_tab import render_data_tab

st.set_page_config(page_title="Centech Scripts", layout="wide")
st.title("Centech Scripts")

tab1, tab2, tab3 = st.tabs(["Payroll", "Financial", "Data"])

with tab1:
    render_payroll_tab()
with tab2:
    render_financial_tab()
with tab3:
    render_data_tab()