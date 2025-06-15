from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from mysql.connector.pooling import MySQLConnectionPool
import mysql.connector
import os
from datetime import datetime, timedelta
from typing import List
import threading, time as time_module
import pytz
import pandas as pd

app = FastAPI()

API_KEY = os.getenv("API_KEY", "your_api_key_here")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# ✅ Setup a global connection pool
pool = MySQLConnectionPool(
    pool_name="main_pool",
    pool_size=21,
    pool_reset_session=True,
    host=os.getenv("DB_HOST"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME")
)

# ✅ Get IST datetime
def get_ist_now():
    return datetime.now(pytz.timezone("Asia/Kolkata"))

# ✅ Log connection activity
def log_connection_activity(user_code, activity, remarks=""):
    try:
        conn = pool.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Connection_Log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_code VARCHAR(50),
                user_role VARCHAR(50),
                activity VARCHAR(50),
                log_time DATETIME,
                remarks TEXT
            )
        """)

        role = "Unknown"
        try:
            cursor.execute("SELECT User_Role FROM User_Credentials WHERE Code = %s", (user_code,))
            result = cursor.fetchone()
            if result:
                role = result[0]
        except:
            pass

        log_time = get_ist_now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO Connection_Log (user_code, user_role, activity, log_time, remarks)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_code, role, activity, log_time, remarks))

        conn.commit()
    except Exception as e:
        print(f"Log Error: {e}")
    finally:
        try:
            cursor.close()
            conn.close()
        except:
            pass

# ✅ Get DB connection and log it
def get_connection(user_code="system"):
    conn = pool.get_connection()
    log_connection_activity(user_code, "get_connection", "Connection opened")
    return conn

# ✅ Close idle 'get_connection' logs
def close_idle_connections(timeout_minutes=5):
    try:
        conn = pool.get_connection()
        cursor = conn.cursor()
        timeout = get_ist_now() - timedelta(minutes=timeout_minutes)
        timeout_str = timeout.strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            UPDATE Connection_Log
            SET activity = 'connection_closed', remarks = 'Closed after timeout'
            WHERE activity = 'get_connection' AND log_time < %s
        """, (timeout_str,))
        conn.commit()
    except Exception as e:
        print(f"Idle connection cleanup failed: {e}")
    finally:
        try:
            cursor.close()
            conn.close()
        except:
            pass

# ✅ Cleanup MySQL Sleep connections if too many open
def cleanup_mysql_and_logs(threshold=100):
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
                        log_connection_activity(user, "kill_thread", f"Killed ID {id} after {time}s")
                    except Exception as kill_err:
                        print(f"Failed to kill thread {id}: {kill_err}")
        cursor.close()
        conn.close()
        close_idle_connections()
    except Exception as e:
        print(f"Cleanup failed: {e}")

# ✅ Periodically run cleanup
threading.Thread(
    target=lambda: (time_module.sleep(5), [cleanup_mysql_and_logs() or time_module.sleep(300) for _ in iter(int, 1)]),
    daemon=True
).start()



# ======================== CONFIGURATION ============================
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
    supervisor_code: str   # <-- Add supervisor_code instead of supervisor_name
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

                # ✅ New logic to resolve supervisor_name based on workstation_name
                resolved_supervisor_name = "Unknown"
                try:
                    # First: get supervisor_code from workstation name
                    cursor.execute("SELECT Supervisor_Code FROM User_Credentials WHERE Name = %s", (entry.workstation_name,))
                    supervisor_code_result = cursor.fetchone()
                    
                    if supervisor_code_result:
                        supervisor_code = supervisor_code_result[0]
                        # Second: get supervisor_name from supervisor_code
                        cursor.execute("SELECT Name FROM User_Credentials WHERE Code = %s", (supervisor_code,))
                        supervisor_name_result = cursor.fetchone()
                        if supervisor_name_result:
                            resolved_supervisor_name = supervisor_name_result[0]
                except Exception as e:
                    print(f"Supervisor name resolution failed: {e}")


                # ✅ Existing logic remains unchanged
                cursor.execute("SELECT COUNT(*) FROM Advisor_Data WHERE date = %s AND advisor_name = %s", 
                               (entry.date, entry.advisor_name))
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
                        entry.workstation_name, resolved_supervisor_name,
                        entry.date, entry.advisor_name
                    ))
                else:
                    supervisor_code = entry.supervisor_code

                    cursor.execute("""INSERT INTO Advisor_Data (
                        date, timestamp, advisor_name, workstation_name, supervisor_code, 
                        running_repair, free_service, paid_service, body_shop, total,
                        align, balance, align_and_balance
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        entry.date, entry.timestamp, entry.advisor_name, entry.workstation_name, supervisor_code,
                        entry.running_repair, entry.free_service, entry.paid_service, entry.body_shop, entry.total,
                        entry.align, entry.balance, entry.align_and_balance
                    ))

            conn.commit()
            return {"status": "success", "message": "Advisor data saved"}


@app.get("/advisors", dependencies=[Depends(verify_api_key)])
def get_advisors(workstation_code: str = Query(...)):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT name FROM User_Credentials
                WHERE Supervisor_Code = %s AND User_Role = 'Advisor'
            """, (workstation_code,))
            advisors = [row[0] for row in cursor.fetchall()]
            return {"advisors": advisors}



    start_of_month = get_ist_now().replace(day=1).strftime("%Y-%m-%d")

    response = {
        "target": None,
        "monthly_totals": None,
        "existing_today": None
    }

    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            # Fetch Target
            cursor.execute("SELECT Target FROM User_Credentials WHERE Name = %s", (workstation_name,))
            row = cursor.fetchone()
            response["target"] = row["Target"] if row else None

            # Fetch Monthly Summary
            cursor.execute("""
                SELECT 
                    SUM(running_repair) AS running_repair,
                    SUM(free_service) AS free_service,
                    SUM(paid_service) AS paid_service,
                    SUM(body_shop) AS body_shop,
                    SUM(total) AS total,
                    SUM(align) AS align,
                    SUM(balance) AS balance,
                    SUM(align_and_balance) AS align_and_balance
                FROM Workstation_Data
                WHERE date >= %s AND workstation_name = %s
            """, (start_of_month, workstation_name))
            response["monthly_totals"] = cursor.fetchone()

            # Fetch Existing Data for Today
            cursor.execute("""
                SELECT running_repair, free_service, paid_service, body_shop,
                       total, align, balance, align_and_balance
                FROM Workstation_Data
                WHERE date = %s AND workstation_name = %s
            """, (today, workstation_name))
            response["existing_today"] = cursor.fetchone()

    return response



@app.post("/workstation/save", dependencies=[Depends(verify_api_key)])
def save_workstation_entry(entry: WorkstationEntry):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) FROM Workstation_Data WHERE date = %s AND workstation_name = %s
            """, (entry.date, entry.workstation_name))
            exists = cursor.fetchone()[0] > 0

            if exists:
                cursor.execute("""
                    UPDATE Workstation_Data
                    SET running_repair = %s, free_service = %s, paid_service = %s,
                        body_shop = %s, total = %s, align = %s, balance = %s,
                        align_and_balance = %s, timestamp = %s, supervisor_name = %s
                    WHERE date = %s AND workstation_name = %s
                """, (
                    entry.running_repair, entry.free_service, entry.paid_service,
                    entry.body_shop, entry.total, entry.align, entry.balance,
                    entry.align_and_balance, entry.timestamp, entry.supervisor_name,
                    entry.date, entry.workstation_name
                ))
            else:
                cursor.execute("""
                    INSERT INTO Workstation_Data (
                        date, timestamp, workstation_name, supervisor_name,
                        running_repair, free_service, paid_service, body_shop,
                        total, align, balance, align_and_balance
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    entry.date, entry.timestamp, entry.workstation_name, entry.supervisor_name,
                    entry.running_repair, entry.free_service, entry.paid_service,
                    entry.body_shop, entry.total, entry.align, entry.balance, entry.align_and_balance
                ))

            conn.commit()
            return {"status": "success", "message": "Workstation data saved successfully."}

@app.get("/workstation/summary", dependencies=[Depends(verify_api_key)])
def workstation_summary(workstation_name: str = Query(...)):
    today = get_ist_now().strftime("%Y-%m-%d")
    start_of_month = get_ist_now().replace(day=1).strftime("%Y-%m-%d")

    print("▶️ [Workstation Summary] Requested for:", workstation_name)
    print("   ↪ Start of month:", start_of_month, "| Today:", today)

    response = {
        "target": None,
        "monthly_totals": None,
        "existing_today": None
    }

    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            # Fetch Target
            cursor.execute("SELECT Target FROM User_Credentials WHERE Name = %s", (workstation_name,))
            row = cursor.fetchone()
            print("   ↪ Target Row:", row)
            response["target"] = row["Target"] if row else None

            # Fetch Monthly Summary
            cursor.execute("""
                SELECT 
                    SUM(running_repair) AS running_repair,
                    SUM(free_service) AS free_service,
                    SUM(paid_service) AS paid_service,
                    SUM(body_shop) AS body_shop,
                    SUM(total) AS total,
                    SUM(align) AS align,
                    SUM(balance) AS balance,
                    SUM(align_and_balance) AS align_and_balance
                FROM Workstation_Data
                WHERE date >= %s AND workstation_name = %s
            """, (start_of_month, workstation_name))
            summary = cursor.fetchone()
            print("   ↪ Monthly Summary:", summary)
            response["monthly_totals"] = summary

            # Fetch Existing Data for Today
            cursor.execute("""
                SELECT running_repair, free_service, paid_service, body_shop,
                       total, align, balance, align_and_balance
                FROM Workstation_Data
                WHERE date = %s AND workstation_name = %s
            """, (today, workstation_name))
            today_data = cursor.fetchone()
            print("   ↪ Existing Today’s Entry:", today_data)
            response["existing_today"] = today_data

    return response



@app.get("/advisor/monthly-summary", dependencies=[Depends(verify_api_key)])
def advisor_summary(start_date: str = Query(...), advisor_names: str = Query(...)):
    advisor_list = advisor_names.split(",")
    print("▶️ [Advisor Summary] Start Date:", start_date)
    print("   ↪ Advisors:", advisor_list)

    if not advisor_list:
        return {"summary": []}

    placeholders = ",".join(["%s"] * len(advisor_list))

    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = f"""
                SELECT advisor_name,
                       SUM(running_repair), SUM(free_service), SUM(paid_service), SUM(body_shop),
                       SUM(total), SUM(align), SUM(balance), SUM(align_and_balance)
                FROM Advisor_Data
                WHERE date >= %s AND advisor_name IN ({placeholders})
                GROUP BY advisor_name
            """
            print("   ↪ Executing SQL:", query)
            cursor.execute(query, [start_date] + advisor_list)
            rows = cursor.fetchall()
            print("   ↪ Summary Results:", rows)

            return {
                "summary": [
                    {
                        "Advisor Name": row[0],
                        "Running Repair": row[1],
                        "Free Service": row[2],
                        "Paid Service": row[3],
                        "Body Shop": row[4],
                        "Total": row[5],
                        "Align": row[6],
                        "Balance": row[7],
                        "Align and Balance": row[8],
                    } for row in rows
                ]
            }
