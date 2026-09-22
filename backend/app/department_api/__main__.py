"""Convenience launcher: python -m app.department_api"""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.department_api.main:app", host="0.0.0.0", port=int(os.getenv("DEPARTMENT_API_PORT", "9101")))
