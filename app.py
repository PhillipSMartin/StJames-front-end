import os
import json
import requests
import pandas as pd
import streamlit as st

from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()

# -------------------
# Config
# -------------------
API_BASE = os.getenv("API_BASE", "").rstrip("/")
API_KEY  = os.getenv("API_KEY", "")
HEADERS  = {"x-api-key": API_KEY, "Content-Type": "application/json"}

if not API_BASE or not API_KEY:
    st.warning("Set API_BASE and API_KEY environment variables.")
    st.stop()

CHANNELS = ["moms", "sojourner", "patch", "test"]

# -------------------
# Helpers
# -------------------
def req(method, path, **kwargs):
    url = f"{API_BASE}{path}"
    headers = kwargs.pop("headers", {})
    headers = {**HEADERS, **headers}
    resp = requests.request(method, url, headers=headers, **kwargs)
    # parse body if present
    body = None
    if resp.content:
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}
    return resp.status_code, body, resp.headers

def list_events(access):
    sc, body, _ = req("GET", f"/events/{access}")
    if sc == 200:
        items = body.get("items", [])
        # derive "date" column from date_id
        for it in items:
            it["date"] = (it.get("date_id", "").split("#")[0])
            # a single "channels" view for table
            chans = []
            for k in ("post", "posting", "posted"):
                for v in it.get(k, []):
                    chans.append(f"{k}:{v}")
            it["channels"] = ", ".join(chans)
        return items
    raise RuntimeError(f"List failed: {sc} {body}")

def enforce_mutual_exclusion(selected_post, selected_posting, selected_posted):
    # Make all sets disjoint by removing overlaps with priority: post > posting > posted
    s1, s2, s3 = set(selected_post or []), set(selected_posting or []), set(selected_posted or [])
    s2 -= s1; s3 -= (s1 | s2)
    return sorted(s1), sorted(s2), sorted(s3)

def create_event(payload):
    sc, body, headers = req("POST", "/events", data=json.dumps(payload))
    return sc, body, headers


def enc(s: str) -> str:
    # encode everything (including '#') so it becomes %23 in the URL
    return quote(s, safe="")  # safe="" => no char left unencoded

def get_event(access, date_id):
    return req("GET", f"/events/{access}/{enc(date_id)}")

def update_event(access, date_id, patch):
    return req("PUT", f"/events/{access}/{enc(date_id)}", data=json.dumps(patch))

def delete_event(access, date_id):
    return req("DELETE", f"/events/{access}/{enc(date_id)}")

# -------------------
# UI
# -------------------
st.set_page_config(page_title="Events Manager", layout="wide")
st.title("Events Manager")

tab_access = st.segmented_control(
    "Access", options=["private", "public"], default="private"
)

with st.sidebar:
    st.subheader("Create new event")
    access_new = st.selectbox("Access", ["private", "public"], index=0, key="create_access")
    date_mode = st.radio("Date input", ["Date only", "Full date_id"])
    date = date_id = ""
    if date_mode == "Date only":
        date = st.date_input("Date (YYYY-MM-DD)").strftime("%Y-%m-%d")
    else:
        date_id = st.text_input("date_id (YYYY-MM-DD#GUID)", placeholder="2025-10-06#<guid>")
    title = st.text_input("Title", placeholder="Choir rehearsal")
    time_ = st.text_input("Time (optional)", placeholder="7:00 pm")
    desc = st.text_area("Description (optional)", height=80)

    st.caption("Channels (mutually exclusive across sections)")
    col1, col2, col3 = st.columns(3)
    with col1:
        post = st.multiselect("post", CHANNELS, key="create_post")
    with col2:
        posting = st.multiselect("posting", CHANNELS, key="create_posting")
    with col3:
        posted = st.multiselect("posted", CHANNELS, key="create_posted")
    post, posting, posted = enforce_mutual_exclusion(post, posting, posted)

    if st.button("Create", use_container_width=True):
        payload = {"access": access_new, "title": title}
        if not title:
            st.error("Title is required.")
        else:
            if date_mode == "Date only":
                payload["date"] = date
            else:
                payload["date_id"] = date_id
            if time_:
                payload["time"] = time_
            if desc:
                payload["description"] = desc
            if post:    payload["post"] = post
            if posting: payload["posting"] = posting
            if posted:  payload["posted"] = posted

            sc, body, headers = create_event(payload)
            if sc == 201:
                loc = headers.get("Location") or (body or {}).get("location")
                st.success(f"Created ✓ {loc or ''}")
                st.experimental_rerun()
            else:
                msg = (body or {}).get("message") or body
                st.error(f"Create failed ({sc}): {msg}")

# List/table
try:
    items = list_events(tab_access)
except Exception as e:
    st.error(str(e))
    items = []

df = pd.DataFrame(items)
if not df.empty:
    # nicer order
    cols = ["date", "title", "time", "description", "channels", "date_id"]
    cols = [c for c in cols if c in df.columns]
    st.dataframe(df[cols], use_container_width=True, hide_index=True)
else:
    st.info("No events for this access yet.")

st.divider()
st.subheader("Edit / Delete")

date_id_sel = st.selectbox(
    "Pick an item to edit", [it["date_id"] for it in items] if items else []
)

if date_id_sel:
    sc, body, _ = get_event(tab_access, date_id_sel)
    if sc == 200 and body:
        with st.form("edit_form", clear_on_submit=False):
            title_e = st.text_input("Title", value=body.get("title", ""))
            time_e  = st.text_input("Time", value=body.get("time", ""))
            desc_e  = st.text_area("Description", value=body.get("description", "") or "", height=80)

            col1, col2, col3 = st.columns(3)
            with col1:
                post_e = st.multiselect("post", CHANNELS, default=body.get("post", []))
            with col2:
                posting_e = st.multiselect("posting", CHANNELS, default=body.get("posting", []))
            with col3:
                posted_e = st.multiselect("posted", CHANNELS, default=body.get("posted", []))
            post_e, posting_e, posted_e = enforce_mutual_exclusion(post_e, posting_e, posted_e)

            c1, c2, c3 = st.columns([1,1,1])
            with c1:
                save = st.form_submit_button("Save", use_container_width=True)
            with c2:
                delete = st.form_submit_button("Delete", use_container_width=True)
            with c3:
                st.write("")  # spacer

        if save:
            patch = {}
            if title_e != body.get("title"):           patch["title"] = title_e
            if time_e != (body.get("time") or ""):     patch["time"] = time_e
            if (desc_e or "") != (body.get("description") or ""): patch["description"] = desc_e
            if post_e != body.get("post", []):         patch["post"] = post_e
            if posting_e != body.get("posting", []):   patch["posting"] = posting_e
            if posted_e != body.get("posted", []):     patch["posted"] = posted_e

            if not patch:
                st.info("No changes.")
            else:
                sc, resp, _ = update_event(tab_access, date_id_sel, patch)
                if sc == 200:
                    st.success("Saved ✓")
                    st.experimental_rerun()
                else:
                    st.error(f"Update failed ({sc}): {(resp or {}).get('message') or resp}")

        if delete:
            sc, _, _ = delete_event(tab_access, date_id_sel)
            if sc in (200, 204):
                st.success("Deleted ✓")
                st.experimental_rerun()
            else:
                st.error(f"Delete failed ({sc})")
    else:
        st.error(f"Fetch failed: {sc} {body}")
