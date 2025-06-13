from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import mysql.connector

app = FastAPI()

# Your MySQL config (use environment variables later in Render)
DB_CONFIG = {
    "host": "your_host",
    "user": "your_user",
    "password": "your_password",
    "database": "your_database"
}

class LoginRequest(BaseModel):
    code: str
    password: str

@app.post("/login")
def login_user(request: LoginRequest):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM User_Credentials WHERE code = %s AND password = %s", (request.code, request.password))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            return {"status": "success", "user": result}
        else:
            raise HTTPException(status_code=401, detail="Invalid credentials")

    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
