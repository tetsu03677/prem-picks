# ui_parts.py
import streamlit as st

def section_header(title: str):
    st.markdown(f"## {title}")

def muted(text: str):
    st.markdown(f"<span style='color:#6b7280'>{text}</span>", unsafe_allow_html=True)

def tag(text: str, kind: str = "info"):
    color = {"info":"#e5e7eb","success":"#dcfce7","danger":"#fee2e2"}.get(kind,"#e5e7eb")
    return f"<span style='background:{color};padding:2px 8px;border-radius:999px'>{text}</span>"

def pill(text: str, kind: str = "info"):
    st.markdown(tag(text, kind), unsafe_allow_html=True)

def kpi(container, label, value):
    with container:
        st.markdown(f"""
        <div style='padding:12px 14px;border:1px solid #eee;border-radius:8px'>
          <div style='color:#6b7280;font-size:12px'>{label}</div>
          <div style='font-size:22px;font-weight:700'>{value}</div>
        </div>
        """, unsafe_allow_html=True)
