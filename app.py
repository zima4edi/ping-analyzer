import re
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Ping Log Analyzer", layout="wide")

tz_utc8 = timezone(timedelta(hours=8))

# Check if Embed Mode is active via URL query param (?embed=true)
is_embedded = st.query_params.get("embed", "false").lower() == "true"

def parse_log(raw_text):
    parsed_records = []
    current_target = None
    current_timestamp = datetime.now(tz=tz_utc8)
    timestamp_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})')

    for line in raw_text.splitlines():
        ts_match = timestamp_pattern.search(line)
        if ts_match:
            try:
                naive_dt = datetime.strptime(ts_match.group(1), "%Y-%m-%d %H:%M:%S")
                current_timestamp = naive_dt.replace(tzinfo=tz_utc8)
            except ValueError:
                pass
            continue

        m = re.search(r'Pinging\s+(\d+\.\d+\.\d+\.\d+)', line)
        if m:
            current_target = m.group(1)
            continue

        if current_target is None:
            continue

        m = re.search(r'time[=<]?(\d+)ms', line, re.IGNORECASE)
        if m:
            latency = float(m.group(1))
            parsed_records.append({
                'timestamp': current_timestamp,
                'target': current_target,
                'latency': latency
            })
            current_timestamp += timedelta(seconds=1)
            continue

        if ("Request timed out" in line or "Destination host unreachable" in line):
            parsed_records.append({
                'timestamp': current_timestamp,
                'target': current_target,
                'latency': np.nan
            })
            current_timestamp += timedelta(seconds=1)

    df = pd.DataFrame(parsed_records)
    if not df.empty:
        df = df.drop_duplicates(subset=['timestamp', 'target'])
    return df


# -------------------------------------------------------------------
# HIDE CONTROLS IN EMBED MODE
# -------------------------------------------------------------------
if not is_embedded:
    st.title("Ping Log Analyzer")
    uploaded_file = st.file_uploader("1. Upload Ping Log File", type=["txt", "log"])
else:
    # Optional: Hide top header padding and footer via CSS when embedded
    st.markdown("""
        <style>
            #MainMenu {visibility: hidden;}
            header {visibility: hidden;}
            footer {visibility: hidden;}
            .block-container {padding-top: 1rem;}
        </style>
    """, unsafe_allow_html=True)
    uploaded_file = None

# Store dataframe in Session State so it persists across views
if uploaded_file is not None:
    raw_data = uploaded_file.getvalue().decode("utf-8", errors="ignore")
    st.session_state['parsed_df'] = parse_log(raw_data)

# Render Plot if parsed data exists
if 'parsed_df' in st.session_state and not st.session_state['parsed_df'].empty:
    df_parsed = st.session_state['parsed_df']
    unique_hosts = list(dict.fromkeys(df_parsed['target'].dropna()))

    # Render control UI only when NOT in embed mode
    if not is_embedded:
        st.success(f"File loaded! {len(df_parsed)} records parsed.")
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            selected_hosts = st.multiselect("Target Host(s):", options=['ALL (All Hosts)'] + unique_hosts, default=['ALL (All Hosts)'])
        with col2:
            hours_selected = st.selectbox("Hours back:", [1, 2, 3, 4], index=1)
        with col3:
            interval_selected = st.selectbox("Interval (min):", [1, 2, 3, 5], index=1)
    else:
        # Default embed settings
        selected_hosts = ['ALL (All Hosts)']
        hours_selected = 2
        interval_selected = 2

    # Filtering & Plotting logic
    max_time = df_parsed['timestamp'].max()
    cutoff_time = max_time - timedelta(hours=hours_selected)
    df_filtered = df_parsed[df_parsed['timestamp'] >= cutoff_time].copy()

    if 'ALL (All Hosts)' not in selected_hosts and len(selected_hosts) > 0:
        df_filtered = df_filtered[df_filtered['target'].isin(selected_hosts)]

    targets = list(dict.fromkeys(df_filtered['target'].dropna()))

    if targets:
        resample_freq = f"{interval_selected}min"
        fig = go.Figure()

        for target in targets:
            target_df = df_filtered[df_filtered['target'] == target].set_index('timestamp')
            resampled = target_df['latency'].resample(resample_freq).mean()

            timestamps = resampled.index
            latencies = resampled.values
            valid = latencies[~np.isnan(latencies)]

            if len(valid) == 0:
                continue

            avg_lat = np.mean(valid)

            fig.add_trace(go.Scatter(
                x=timestamps,
                y=latencies,
                mode='lines+markers',
                name=f'{target} (Avg: {avg_lat:.1f} ms)',
                marker=dict(size=5),
                hovertemplate=f"<b>{target}</b><br>Time: %{{x|%H:%M}}<br>Latency: %{{y:.1f}} ms<extra></extra>"
            ))

        plot_date = max_time.strftime("%Y-%m-%d")
        plot_title = f"<b>Host Comparison</b> [{plot_date} (UTC+8)] | Last {hours_selected}h"

        fig.update_layout(
            title=plot_title,
            template="plotly_dark",
            xaxis=dict(title="Time (HH:MM UTC+8)", tickformat="%H:%M"),
            yaxis_title="Avg Latency (ms)",
            hovermode="x unified",
            height=500,
            margin=dict(l=40, r=40, t=50, b=40)
        )

        # Displays ONLY the interactive plot
        st.plotly_chart(fig, use_container_width=True)
elif is_embedded:
    st.info("No data available to display in view-only mode.")
