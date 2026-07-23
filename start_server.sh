#!/bin/bash
# Auto-restart server on crash
cd /c/Users/admin/Documents/trae_projects/video_marketing_app
while true; do
    echo "[$(date)] Starting server..."
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload 2>&1
    echo "[$(date)] Server crashed, restarting in 3s..."
    sleep 3
done
