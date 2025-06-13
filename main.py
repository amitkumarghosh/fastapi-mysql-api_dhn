from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.security.api_key import APIKeyHeader
import os
import mysql
from pydantic import BaseModel

API_KEY = os.getenv("API_KEY", "CDy4mY7O0YvuHD0cNJ8BmtGMukr_22MsabUomCx-CNk")  # Store securely in real projects
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

class LoginRequest(BaseModel):
    code: str
    password: str

app = FastAPI()

def verify_api_key(api_key: str = Depends(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Could not validate API key")

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
        return {
            "status": "success",
            "user": user  # this must be a dictionary
        }
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")


@app.get("/")
def root():
    return {"message": "API is live. Use POST /login with API key."}
