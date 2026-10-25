"""共用的樣式與號碼球渲染。"""
from typing import List, Union

import streamlit as st


def setup():
    st.set_page_config(page_title="BINGO 對獎與分析", page_icon="🎰", layout="wide")
    st.markdown("""
    <style>
        .ball-container { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
        .ball { width: 42px; height: 42px; line-height: 42px; border-radius: 50%; text-align: center; font-weight: 900; font-size: 18px; box-shadow: 2px 2px 5px rgba(0,0,0,0.2); }
        .ball-normal { background-color: #FFD700; color: #333; }
        .ball-super { background-color: #FF3B30; color: #FFF; }
        .ball-user { background-color: #007AFF; color: #FFF; }
        .ball-match { background-color: #34C759; color: #FFF; }
        .stTabs [data-baseweb="tab-list"] { justify-content: center; }
        div[data-testid="stMetricValue"] { font-size: 2rem; }
        .time-tag { color: #666; font-size: 0.85em; margin-left: 10px; background: #eee; padding: 2px 8px; border-radius: 12px; }
        .info-tag { background: linear-gradient(90deg, #4b6cb7, #182848); color: white; padding: 4px 12px; border-radius: 15px; font-weight: bold; margin-bottom: 10px; display: inline-block; }
    </style>
    """, unsafe_allow_html=True)


def render_balls(nums: Union[List[int], int], btype: str = "normal") -> str:
    nums = [nums] if isinstance(nums, int) else sorted(nums)
    html = "<div class='ball-container'>"
    for n in nums: html += f"<div class='ball ball-{btype}'>{n:02d}</div>"
    return html + "</div>"
