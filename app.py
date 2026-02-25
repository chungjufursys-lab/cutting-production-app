import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import os
import re

# =========================
# 기본 설정
# =========================
st.set_page_config(page_title="재단공정 작업관리", layout="wide")
st.title("재단공정 작업관리 시스템")

EQUIP_TABS = ["1호기", "2호기", "네스팅", "6호기", "곡면"]

EQUIPMENT_MAP = {
    "판넬컷터 #1": "1호기",
    "판넬컷터 #2": "2호기",
    "네스팅 #1": "네스팅",
    "판넬컷터 #6": "6호기",
    "판넬컷터 #3(곡면)": "곡면",
}

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# =========================
# DB 연결
# =========================
conn = sqlite3.connect("cutting.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS work_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment TEXT,
    file_name TEXT,
    file_path TEXT,
    uploaded_at TEXT,
    status TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_order_id INTEGER,
    lot_key TEXT,
    qty INTEGER,
    move_card_no TEXT,
    status TEXT,
    done_at TEXT
)
""")
conn.commit()

# =========================
# 상태 재계산 (VOID 보호)
# =========================
def update_work_order_status(work_order_id):
    row = pd.read_sql("SELECT status FROM work_orders WHERE id=?", conn, params=(work_order_id,))
    if len(row) == 0:
        return 0,0,"UNKNOWN"

    if row.iloc[0]["status"] == "VOID":
        df = pd.read_sql("SELECT status FROM lots WHERE work_order_id=?", conn, params=(work_order_id,))
        total = len(df)
        done = (df["status"]=="DONE").sum()
        return done,total,"VOID"

    df = pd.read_sql("SELECT status FROM lots WHERE work_order_id=?", conn, params=(work_order_id,))
    total = len(df)
    done = (df["status"]=="DONE").sum()

    if total==0 or done==0:
        new_status="WAITING"
    elif done<total:
        new_status="IN_PROGRESS"
    else:
        new_status="COMPLETED"

    cur.execute("UPDATE work_orders SET status=? WHERE id=?", (new_status,work_order_id))
    conn.commit()
    return done,total,new_status

# =========================
# 🔍 이동카드 검색 (ENTER + 버튼 모두 동작)
# =========================
st.markdown("## 🔍 이동카드번호 통합 검색")

with st.form("move_search_form"):
    move_search = st.text_input("이동카드번호 입력 (예: C202602-36114)")
    search_submit = st.form_submit_button("검색")

if search_submit:
    if move_search.strip()=="":
        st.warning("이동카드번호를 입력하세요.")
    else:
        result = pd.read_sql("""
            SELECT w.equipment, w.file_name, l.lot_key, l.qty, l.status
            FROM lots l
            JOIN work_orders w ON w.id=l.work_order_id
            WHERE l.move_card_no=?
        """, conn, params=(move_search.strip(),))

        if len(result)==0:
            st.error("검색 결과가 없습니다.")
        else:
            st.success(f"{len(result)}건 발견")
            st.dataframe(result,use_container_width=True)

st.divider()

# =========================
# 업로드
# =========================
st.sidebar.header("관리자")
uploaded = st.sidebar.file_uploader("ERP 엑셀 업로드", type=["xlsx"])

def detect_equipment_column(df):
    for col in df.columns:
        sample=df[col].dropna().astype(str).head(40)
        if sample.str.contains("판넬컷터|네스팅",regex=True).any():
            return col
    return None

def detect_lot_column(df):
    for col in reversed(df.columns):
        sample=df[col].dropna().astype(str).head(80)
        if sample.str.contains(r"\d+T-",regex=True).any():
            return col
    return None

def detect_qty_column(df,lot_col):
    cols=list(df.columns)
    idx=cols.index(lot_col)
    for col in cols[idx+1:]:
        s=df[col].dropna().head(50)
        if len(s)==0: continue
        try:
            float(s.iloc[0])
            return col
        except: continue
    return None

def detect_move_card_column(df):
    pattern=r"C\d{6}-\d+"
    for col in df.columns:
        sample=df[col].dropna().astype(str).head(100)
        if sample.str.contains(pattern,regex=True).any():
            return col
    return None

if uploaded:
    df=pd.read_excel(uploaded)
    equip_col=detect_equipment_column(df)
    lot_col=detect_lot_column(df)
    qty_col=detect_qty_column(df,lot_col) if lot_col else None
    move_col=detect_move_card_column(df)

    st.sidebar.write("자동 감지 결과")
    st.sidebar.write(f"설비: {equip_col}")
    st.sidebar.write(f"로트: {lot_col}")
    st.sidebar.write(f"수량: {qty_col}")
    st.sidebar.write(f"이동카드: {move_col}")

    if st.sidebar.button("작업지시 등록"):
        safe_name=f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded.name}"
        saved_path=os.path.join(UPLOAD_DIR,safe_name)

        with open(saved_path,"wb") as f:
            f.write(uploaded.getbuffer())

        for equip_raw,sub in df.groupby(equip_col):
            equip=EQUIPMENT_MAP.get(str(equip_raw).strip())
            if not equip: continue

            cur.execute("""
                INSERT INTO work_orders (equipment,file_name,file_path,uploaded_at,status)
                VALUES (?,?,?,?,?)
            """,(equip,uploaded.name,saved_path,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "WAITING"))
            work_order_id=cur.lastrowid

            for _,r in sub.iterrows():
                lot_key=r.get(lot_col)
                qty_val=r.get(qty_col)
                move_no=r.get(move_col) if move_col else None

                if pd.isna(lot_key): continue
                try:
                    qty=int(float(qty_val))
                except: continue

                cur.execute("""
                    INSERT INTO lots (work_order_id,lot_key,qty,move_card_no,status,done_at)
                    VALUES (?,?,?,?,?,NULL)
                """,(work_order_id,str(lot_key),qty,str(move_no),"WAITING"))

            conn.commit()
            update_work_order_status(work_order_id)

        st.sidebar.success("작업지시 등록 완료")
        st.rerun()

# =========================
# 설비 탭
# =========================
tabs=st.tabs(EQUIP_TABS)

for i,equip in enumerate(EQUIP_TABS):
    with tabs[i]:

        show_completed=st.checkbox("완료 작업지시 포함",key=f"comp_{equip}")
        show_void=st.checkbox("취소 작업지시 포함",key=f"void_{equip}")

        query="SELECT * FROM work_orders WHERE equipment=?"
        params=[equip]

        if not show_completed:
            query+=" AND status!='COMPLETED'"
        if not show_void:
            query+=" AND status!='VOID'"

        query+=" ORDER BY uploaded_at DESC"
        work_orders=pd.read_sql(query,conn,params=params)

        # KPI (매수합계)
        kpi_df=pd.read_sql("""
            SELECT l.qty,l.status,l.done_at
            FROM lots l
            JOIN work_orders w ON w.id=l.work_order_id
            WHERE w.equipment=? AND w.status!='VOID'
        """,conn,params=(equip,))

        unfinished_qty=int(kpi_df.loc[kpi_df["status"]=="WAITING","qty"].sum()) if len(kpi_df) else 0

        today_done_qty=pd.read_sql("""
            SELECT COALESCE(SUM(l.qty),0) as total
            FROM lots l
            JOIN work_orders w ON w.id=l.work_order_id
            WHERE w.equipment=?
              AND w.status!='VOID'
              AND l.status='DONE'
              AND date(l.done_at)=date('now','localtime')
        """,conn,params=(equip,)).iloc[0]["total"]

        in_progress_cnt=pd.read_sql("""
            SELECT COUNT(*) as c
            FROM work_orders
            WHERE equipment=? AND status='IN_PROGRESS'
        """,conn,params=(equip,)).iloc[0]["c"]

        c1,c2,c3=st.columns(3)
        c1.metric("진행중 작업지시",in_progress_cnt)
        c2.metric("미완료 원장 (매수)",unfinished_qty)
        c3.metric("오늘 완료 원장 (매수)",today_done_qty)

        st.divider()

        if len(work_orders)==0:
            st.info("작업지시 없음")
            continue

        left,right=st.columns([1,2])

        with left:
            options=[]
            for _,r in work_orders.iterrows():
                done,total,status=update_work_order_status(r["id"])
                options.append((r["id"],f"{status} | {done}/{total}\n{r['file_name']}"))

            selected=st.radio("작업지시 선택",options,format_func=lambda x:x[1])
            selected_id=selected[0]

        with right:
            wo_info=pd.read_sql("SELECT * FROM work_orders WHERE id=?",conn,params=(selected_id,))
            wo_status=wo_info.iloc[0]["status"]

            # 취소 버튼
            if wo_status!="VOID":
                if st.button("⛔ 작업지시 취소",key=f"void_{equip}_{selected_id}"):
                    cur.execute("UPDATE work_orders SET status='VOID' WHERE id=?",(selected_id,))
                    conn.commit()
                    st.rerun()

            # 다운로드
            if os.path.exists(wo_info.iloc[0]["file_path"]):
                with open(wo_info.iloc[0]["file_path"],"rb") as f:
                    st.download_button("📥 원본 엑셀 다운로드",
                                       f,
                                       file_name=wo_info.iloc[0]["file_name"],
                                       key=f"down_{equip}_{selected_id}")

            st.divider()

            lots_df=pd.read_sql("SELECT * FROM lots WHERE work_order_id=?",conn,params=(selected_id,))

            for _,r in lots_df.iterrows():
                c1,c2,c3,c4=st.columns([5,1,1,1])
                c1.write(r["lot_key"])
                c2.write(r["qty"])
                c3.write(r["status"])

                if wo_status=="VOID":
                    c4.write("-")
                    continue

                if r["status"]=="WAITING":
                    if c4.button("완료",key=f"done_{r['id']}"):
                        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        cur.execute("UPDATE lots SET status='DONE',done_at=? WHERE id=?",
                                    (now,r["id"]))
                        conn.commit()
                        update_work_order_status(selected_id)
                        st.rerun()
                else:
                    if c4.button("완료취소",key=f"undo_{r['id']}"):
                        cur.execute("UPDATE lots SET status='WAITING',done_at=NULL WHERE id=?",
                                    (r["id"],))
                        conn.commit()
                        update_work_order_status(selected_id)
                        st.rerun()