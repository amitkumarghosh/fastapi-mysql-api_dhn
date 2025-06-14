from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from mysql.connector.pooling import MySQLConnectionPool
import mysql.connector
import os
from datetime import datetime
from typing import List
import threading, time

app = FastAPI()

API_KEY = os.getenv("API_KEY", "your_api_key_here")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# ✅ Setup a global connection pool (21 connections)
pool = MySQLConnectionPool(
    pool_name="main_pool",
    pool_size=21,
    pool_reset_session=True,
    host=os.getenv("DB_HOST"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME")
)

# ✅ Connection Logger
def log_connection_activity(user_code, activity, remarks=""):
    try:
        conn = pool.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Connection_Log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_code VARCHAR(50),
                activity VARCHAR(50),
                log_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                remarks TEXT
            )
            """
        )
        cursor.execute(
            "INSERT INTO Connection_Log (user_code, activity, remarks) VALUES (%s, %s, %s)",
            (user_code, activity, remarks)
        )
        conn.commit()
    except Exception as e:
        print(f"Log Error: {e}")
    finally:
        try:
            cursor.close()
            conn.close()
        except:
            pass

# ✅ Helper to get a connection from the pool
def get_connection():
    conn = pool.get_connection()
    log_connection_activity("system", "get_connection", "Connection opened")
    return conn

# ✅ Kill Inactive Connections
def cleanup_inactive_connections(threshold=100):
    try:
        conn = pool.get_connection()
        cursor = conn.cursor()
        cursor.execute("SHOW STATUS LIKE 'Threads_connected';")
        threads_connected = int(cursor.fetchone()[1])

        if threads_connected > threshold:
            cursor.execute("SHOW PROCESSLIST;")
            processes = cursor.fetchall()
            for proc in processes:
                id, user, host, db, command, time, state, info = proc[:8]
                if command == 'Sleep' and time > 10:
                    try:
                        cursor.execute(f"KILL {id};")
                        log_connection_activity("system", "kill_thread", f"Killed ID {id} after {time}s")
                    except Exception as kill_err:
                        print(f"Failed to kill thread {id}: {kill_err}")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Cleanup failed: {e}")

# ✅ Periodic Cleanup
threading.Thread(target=lambda: (time.sleep(5), [cleanup_inactive_connections() or time.sleep(300) for _ in iter(int, 1)]), daemon=True).start()


def verify_api_key(api_key: str = Depends(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Could not validate API key")

# ======================== MODELS ============================

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
    supervisor_name: str
    running_repair: int
    free_service: int
    paid_service: int
    body_shop: int
    total: int
    align: int
    balance: int
    align_and_balance: int

# ======================== ENDPOINTS ============================

@app.post("/login", dependencies=[Depends(verify_api_key)])
def login(request: LoginRequest):
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM User_Credentials WHERE code = %s AND password = %s", (request.code, request.password))
            user = cursor.fetchone()
            if user:
                return {"status": "success", "user": user}
            else:
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
            supervisor_code = result[0] if result else None

            supervisor_name = "Unknown"
            if supervisor_code:
                cursor.execute("SELECT Name FROM User_Credentials WHERE Code = %s", (supervisor_code,))
                result = cursor.fetchone()
                if result:
                    supervisor_name = result[0]

            return {"supervisor_name": supervisor_name}


@app.post("/advisor/save", dependencies=[Depends(verify_api_key)])
def save_advisor_data(entries: List[AdvisorEntry]):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            for entry in entries:
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
                        entry.workstation_name, entry.supervisor_name,
                        entry.date, entry.advisor_name
                    ))
                else:
                    cursor.execute("""
                        INSERT INTO Advisor_Data (
                            date, timestamp, advisor_name, workstation_name, supervisor_name,
                            running_repair, free_service, paid_service, body_shop, total,
                            align, balance, align_and_balance
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        entry.date, entry.timestamp, entry.advisor_name, entry.workstation_name, entry.supervisor_name,
                        entry.running_repair, entry.free_service, entry.paid_service, entry.body_shop, entry.total,
                        entry.align, entry.balance, entry.align_and_balance
                    ))
            conn.commit()
            return {"status": "success", "message": "Advisor data saved"}


@app.get("/advisor/list", dependencies=[Depends(verify_api_key)])
def get_advisors(supervisor_code: str = Query(...)):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT name FROM User_Credentials WHERE Supervisor_Code = %s AND User_Role = 'Advisor'
            """, (supervisor_code,))
            advisors = [row[0] for row in cursor.fetchall()]
            return {"advisors": advisors}


@app.get("/advisor/monthly-summary", dependencies=[Depends(verify_api_key)])
def advisor_summary(supervisor_code: str = Query(...), start_date: str = Query(...)):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT name FROM User_Credentials 
                WHERE Supervisor_Code = %s AND User_Role = 'Advisor'
            """, (supervisor_code,))
            advisors = [row[0] for row in cursor.fetchall()]
            if not advisors:
                return {"data": []}

            placeholders = ",".join(["%s"] * len(advisors))
            query = f"""
                SELECT advisor_name,
                       SUM(running_repair), SUM(free_service), SUM(paid_service), SUM(body_shop),
                       SUM(total), SUM(align), SUM(balance), SUM(align_and_balance)
                FROM Advisor_Data
                WHERE date >= %s AND advisor_name IN ({placeholders})
                GROUP BY advisor_name
            """
            cursor.execute(query, [start_date] + advisors)
            rows = cursor.fetchall()

            return {
                "data": rows,
                "columns": ["Advisor Name", "Running Repair", "Free Service", "Paid Service", 
                            "Body Shop", "Total", "Align", "Balance", "Align and Balance"]
            }
