# prem-picks/google_sheets_client.py
# -*- coding: utf-8 -*-
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def _get_creds():
    info = st.secrets["gcp_service_account"]
    return Credentials.from_service_account_info(info, scopes=SCOPES)

def _get_client():
    return gspread.authorize(_get_creds())

def _get_sheet(sheet_name="bets"):
    key = st.secrets["sheets"]["sheet_id"]
    return _get_client().open_by_key(key).worksheet(sheet_name)

def append_bet(gw, match, user, bet_team, stake, odds, timestamp):
    sh = _get_sheet("bets")
    sh.append_row([gw, match, user, bet_team, stake, odds, timestamp])
