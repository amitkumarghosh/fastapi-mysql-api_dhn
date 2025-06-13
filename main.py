from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.security.api_key import APIKeyHeader
import os

API_KEY = os.getenv("API_KEY", "CDy4mY7O0YvuHD0cNJ8BmtGMukr_22MsabUomCx-CNk")  # Store securely in real projects
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

app = FastAPI()

def verify_api_key(api_key: str = Depends(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Could not validate API key")

@app.post("/login", dependencies=[Depends(verify_api_key)])
async def login(payload: dict):
    code = payload.get("code")
    password = payload.get("password")
    # Your authentication logic
    return {"message": f"Login successful for {code}"}

@app.get("/")
def root():
    return {"message": "API is live. Use POST /login with API key."}
