from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from mysql.connector.pooling import MySQLConnectionPool
from typing import List
from datetime import datetime, timedelta
import mysql.connector, pytz, os, threading, time as time_module

# ----------------- Configuration --------------------
app = FastAPI()
API_KEY = os.getenv("API_KEY", "your_api_key_here")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# ----------------- MySQL Connection Pool -------------
pool = MySQLConnectionPool(
    pool_name="main_pool",
    pool_size=20,
    pool_reset_session=True,
    host=os.getenv("DB_HOST"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME")
)

def get_connection():
    return pool.get_connection()

# ----------------- Timezone Helpers ------------------
def get_ist_now():
    return datetime.now(pytz.timezone("Asia/Kolkata"))

# ----------------- Security --------------------------
def verify_api_key(api_key: str = Depends(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")

# ----------------- Pydantic Models -------------------
class LoginRequest(BaseModel):
    code: str
    password: str

class InTimeRequest(BaseModel):
    code: str
    name: str
    workstation: str
    in_time: str
    photo_link: str
    supervisor_name: str

class OutTimeRequest(BaseModel):
    code: str
    out_time: str
    photo_link: str
    shift_duration: str

class CheckInRequest(BaseModel):
    code: str

class AdvisorEntry(BaseModel):
    date: str
    timestamp: str
    advisor_name: str
    workstation_name: str
    supervisor_name: str  # supervisor_code is passed here
    running_repair: int
    free_service: int
    paid_service: int
    body_shop: int
    total: int
    align: int
    balance: int
    align_and_balance: int

class WorkstationEntry(BaseModel):
    date: str
    timestamp: str
    workstation_name: str
    supervisor_name: str
    running_repair: int
    free_service: int
    paid_service: int
    body_shop: int
    total: int
    align: int
    balance: int
    align_and_balance: int

# ----------------- Supervisor Name Resolver -----------
def resolve_supervisor_name(supervisor_code: str):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT Name FROM User_Credentials WHERE Code = %s", (supervisor_code,))
        result = cursor.fetchone()
        return result[0] if result else "Unknown"
    except:
        return "Unknown"
    finally:
        cursor.close()
        conn.close()

# ==================== API ENDPOINTS ====================

@app.post("/login", dependencies=[Depends(verify_api_key)])
def login(request: LoginRequest):
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM User_Credentials WHERE code = %s AND password = %s", (request.code, request.password))
            user = cursor.fetchone()
            if user:
                return {"status": "success", "user": user}
            raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/attendance/in", dependencies=[Depends(verify_api_key)])
def mark_in_time(data: InTimeRequest):
    today = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM Attendance WHERE Code = %s AND Attendance_Date = %s", (data.code, today))
            if cursor.fetchone():
                return {"status": "exists", "message": "Already marked In Time"}

            cursor.execute("""
                INSERT INTO Attendance (Code, Name, Workstation_Name, Attendance_Date, In_Time, In_Time_Photo_Link, Supervisor_Name)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (data.code, data.name, data.workstation, today, data.in_time, data.photo_link, data.supervisor_name))
            conn.commit()
            return {"status": "success", "message": "In Time recorded"}

@app.post("/attendance/out", dependencies=[Depends(verify_api_key)])
def mark_out_time(data: OutTimeRequest):
    today = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE Attendance
                SET Out_Time = %s, Out_Time_Photo_Link = %s, Shift_Duration = %s
                WHERE Code = %s AND Attendance_Date = %s
            """, (data.out_time, data.photo_link, data.shift_duration, data.code, today))
            conn.commit()
            return {"status": "success", "message": "Out Time recorded"}

@app.post("/attendance/check-in", dependencies=[Depends(verify_api_key)])
def has_in_time_recorded(data: CheckInRequest):
    today = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT In_Time FROM Attendance WHERE Code = %s AND Attendance_Date = %s", (data.code, today))
            result = cursor.fetchone()
            return {"has_in_time": bool(result), "in_time": result[0] if result else None}

@app.get("/workstations", dependencies=[Depends(verify_api_key)])
def get_workstations():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT DISTINCT Name FROM User_Credentials WHERE User_Role = 'Workstation'")
            rows = cursor.fetchall()
            return {"workstations": sorted([row[0] for row in rows if row[0]])}

@app.get("/supervisor-name", dependencies=[Depends(verify_api_key)])
def get_supervisor_name(code: str = Query(...)):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT Supervisor_Code FROM User_Credentials WHERE Code = %s", (code,))
            result = cursor.fetchone()
            return {"supervisor_name": result[0] if result else None}

@app.post("/advisor/save", dependencies=[Depends(verify_api_key)])
def save_advisor_data(entries: List[AdvisorEntry]):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            for entry in entries:
                supervisor_resolved = resolve_supervisor_name(entry.supervisor_name)

                cursor.execute("SELECT COUNT(*) FROM Advisor_Data WHERE date = %s AND advisor_name = %s", (entry.date, entry.advisor_name))
                exists = cursor.fetchone()[0] > 0

                if exists:
                    cursor.execute("""
                        UPDATE Advisor_Data
                        SET running_repair=%s, free_service=%s, paid_service=%s, body_shop=%s,
                            total=%s, align=%s, balance=%s, align_and_balance=%s, timestamp=%s,
                            workstation_name=%s, supervisor_name=%s
                        WHERE date=%s AND advisor_name=%s
                    """, (
                        entry.running_repair, entry.free_service, entry.paid_service, entry.body_shop,
                        entry.total, entry.align, entry.balance, entry.align_and_balance, entry.timestamp,
                        entry.workstation_name, supervisor_resolved, entry.date, entry.advisor_name
                    ))
                else:
                    cursor.execute("""
                        INSERT INTO Advisor_Data (
                            date, timestamp, advisor_name, workstation_name, supervisor_name,
                            running_repair, free_service, paid_service, body_shop, total,
                            align, balance, align_and_balance
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        entry.date, entry.timestamp, entry.advisor_name, entry.workstation_name, supervisor_resolved,
                        entry.running_repair, entry.free_service, entry.paid_service, entry.body_shop, entry.total,
                        entry.align, entry.balance, entry.align_and_balance
                    ))
            conn.commit()
            return {"status": "success", "message": "Advisor data saved"}

@app.get("/advisors", dependencies=[Depends(verify_api_key)])
def get_advisors(workstation_code: str = Query(...)):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT name FROM User_Credentials WHERE Supervisor_Code = %s AND User_Role = 'Advisor'", (workstation_code,))
            advisors = [row[0] for row in cursor.fetchall()]
            return {"advisors": advisors}

@app.post("/workstation/save", dependencies=[Depends(verify_api_key)])
def save_workstation_entry(entry: WorkstationEntry):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM Workstation_Data WHERE date = %s AND workstation_name = %s", (entry.date, entry.workstation_name))
            exists = cursor.fetchone()[0] > 0

            if exists:
                cursor.execute("""
                    UPDATE Workstation_Data
                    SET running_repair=%s, free_service=%s, paid_service=%s, body_shop=%s,
                        total=%s, align=%s, balance=%s, align_and_balance=%s, timestamp=%s, supervisor_name=%s
                    WHERE date=%s AND workstation_name=%s
                """, (
                    entry.running_repair, entry.free_service, entry.paid_service, entry.body_shop,
                    entry.total, entry.align, entry.balance, entry.align_and_balance, entry.timestamp,
                    entry.supervisor_name, entry.date, entry.workstation_name
                ))
            else:
                cursor.execute("""
                    INSERT INTO Workstation_Data (
                        date, timestamp, workstation_name, supervisor_name, running_repair, free_service,
                        paid_service, body_shop, total, align, balance, align_and_balance
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    entry.date, entry.timestamp, entry.workstation_name, entry.supervisor_name,
                    entry.running_repair, entry.free_service, entry.paid_service,
                    entry.body_shop, entry.total, entry.align, entry.balance, entry.align_and_balance
                ))
            conn.commit()
            return {"status": "success", "message": "Workstation data saved"}

@app.get("/workstation/summary", dependencies=[Depends(verify_api_key)])
def workstation_summary(workstation_name: str = Query(...)):
    today = get_ist_now().strftime("%Y-%m-%d")
    start_of_month = get_ist_now().replace(day=1).strftime("%Y-%m-%d")

    response = {"target": None, "monthly_totals": None, "existing_today": None}

    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT Target FROM User_Credentials WHERE Name = %s", (workstation_name,))
            row = cursor.fetchone()
            response["target"] = row["Target"] if row else None

            cursor.execute("""
                SELECT SUM(running_repair) AS running_repair, SUM(free_service) AS free_service,
                       SUM(paid_service) AS paid_service, SUM(body_shop) AS body_shop, SUM(total) AS total,
                       SUM(align) AS align, SUM(balance) AS balance, SUM(align_and_balance) AS align_and_balance
                FROM Workstation_Data
                WHERE date >= %s AND workstation_name = %s
            """, (start_of_month, workstation_name))
            response["monthly_totals"] = cursor.fetchone()

            cursor.execute("""
                SELECT running_repair, free_service, paid_service, body_shop, total,
                       align, balance, align_and_balance
                FROM Workstation_Data
                WHERE date = %s AND workstation_name = %s
            """, (today, workstation_name))
            response["existing_today"] = cursor.fetchone()

    return response
