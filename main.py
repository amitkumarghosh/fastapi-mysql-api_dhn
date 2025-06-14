# from fastapi import FastAPI, Depends, HTTPException
# from fastapi.security.api_key import APIKeyHeader
# from pydantic import BaseModel
# import mysql.connector
# import os

# app = FastAPI()

# API_KEY = os.getenv("API_KEY", "your_api_key_here")
# API_KEY_NAME = "X-API-Key"
# api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# def verify_api_key(api_key: str = Depends(api_key_header)):
#     if api_key != API_KEY:
#         raise HTTPException(status_code=403, detail="Could not validate API key")

# # ✅ Define the expected request body
# class LoginRequest(BaseModel):
#     code: str
#     password: str

# @app.post("/login", dependencies=[Depends(verify_api_key)])
# def login(request: LoginRequest):
#     conn = mysql.connector.connect(
#     host=os.getenv("DB_HOST"),
#     user=os.getenv("DB_USER"),
#     password=os.getenv("DB_PASSWORD"),
#     database=os.getenv("DB_NAME")
#     )
#     cursor = conn.cursor(dictionary=True)
#     cursor.execute("SELECT * FROM User_Credentials WHERE code = %s AND password = %s", (request.code, request.password))
#     user = cursor.fetchone()
#     cursor.close()
#     conn.close()

#     if user:
#         return {
#             "status": "success",
#             "user": user
#         }
#     else:
#         raise HTTPException(status_code=401, detail="Invalid credentials")

#==========================================================


from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
import mysql.connector
import os
from datetime import datetime

app = FastAPI()

API_KEY = os.getenv("API_KEY", "your_api_key_here")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key(api_key: str = Depends(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Could not validate API key")

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

@app.post("/login", dependencies=[Depends(verify_api_key)])
def login(request: LoginRequest):
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM User_Credentials WHERE code = %s AND password = %s", (request.code, request.password))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    if user:
        return {"status": "success", "user": user}
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/attendance/in", dependencies=[Depends(verify_api_key)])
def mark_in_time(data: InTimeRequest):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Attendance WHERE Code = %s AND Attendance_Date = %s", (data.code, today))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        return {"status": "exists", "message": "Already marked In Time"}

    cursor.execute("""
        INSERT INTO Attendance (Code, Name, Workstation_Name, Attendance_Date, In_Time, In_Time_Photo_Link, Supervisor_Name)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (data.code, data.name, data.workstation, today, data.in_time, data.photo_link, data.supervisor_name))
    conn.commit()
    cursor.close()
    conn.close()
    return {"status": "success", "message": "In Time recorded"}

@app.post("/attendance/out", dependencies=[Depends(verify_api_key)])
def mark_out_time(data: OutTimeRequest):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE Attendance
        SET Out_Time = %s, Out_Time_Photo_Link = %s, Shift_Duration = %s
        WHERE Code = %s AND Attendance_Date = %s
    """, (data.out_time, data.photo_link, data.shift_duration, data.code, today))
    conn.commit()
    cursor.close()
    conn.close()
    return {"status": "success", "message": "Out Time recorded"}

@app.post("/attendance/check-in", dependencies=[Depends(verify_api_key)])
def has_in_time_recorded(data: CheckInRequest):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )
    cursor = conn.cursor()
    cursor.execute("SELECT In_Time FROM Attendance WHERE Code = %s AND Attendance_Date = %s", (data.code, today))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return {"has_in_time": bool(result), "in_time": result[0] if result else None}

@app.get("/workstations", dependencies=[Depends(verify_api_key)])
def get_workstations():
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT Name FROM User_Credentials WHERE User_Role = 'Workstation'")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    workstations = [row[0] for row in rows if row[0]]
    return {"workstations": sorted(workstations)}


from fastapi import Query

@app.get("/supervisor-name", dependencies=[Depends(verify_api_key)])
def get_supervisor_name(code: str = Query(...)):
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )
    cursor = conn.cursor()
    cursor.execute("""
        SELECT Supervisor_Code 
        FROM User_Credentials 
        WHERE Code = %s AND Supervisor_Code IS NOT NULL
    """, (code,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    return {"supervisor_name": row[0] if row else "Unknown"}
