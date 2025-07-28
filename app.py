import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import aiofiles
from asyncio_throttle import Throttler
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from database import SessionLocal, engine, init_db
from models import Employee, ProcessingJob, ProcessingResult
from tasks import process_excel_task, retry_failed_processing
from utils import read_excel_data, validate_excel_file

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Aadhar Processing API", version="1.0.0")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

UPLOAD_DIR = Path("uploads")
RESULTS_DIR = Path("results")
UPLOAD_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

throttler = Throttler(rate_limit=5, period=60)

@app.on_event("startup")
async def startup_event():
    await init_db()

@app.get("/", response_class=HTMLResponse)
async def upload_form(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})

@app.get("/status", response_class=HTMLResponse)
async def status_page(request: Request):
    return templates.TemplateResponse("status.html", {"request": request})

@app.post("/upload")
async def upload_excel(
    file: UploadFile = File(...),
    sheet_name: str = Form("Sheet1")
):
    if not file.filename or not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only Excel files are allowed")
    
    job_id = str(uuid.uuid4())
    file_path = UPLOAD_DIR / f"{job_id}_{file.filename}"
    
    async with aiofiles.open(file_path, 'wb') as f:
        content = await file.read()
        await f.write(content)
    
    try:
        employees = read_excel_data(str(file_path), sheet_name)
        if not employees:
            raise HTTPException(status_code=400, detail="No valid employee data found in the Excel file")
        
        async with SessionLocal() as db:
            job = ProcessingJob(
                id=job_id,
                filename=file.filename,
                sheet_name=sheet_name,
                total_rows=len(employees),
                status="queued",
                created_at=datetime.utcnow()
            )
            db.add(job)
            await db.commit()
            
            for emp in employees:
                db.add(Employee(
                    job_id=job_id,
                    empno=emp.empno,
                    employee_name=emp.employee_name,
                    pan_no=emp.pan_no,
                    aadhar_no=emp.aadhar_no
                ))
            await db.commit()
        
        asyncio.create_task(process_excel_task(job_id, str(file_path), sheet_name))
        
        return {
            "job_id": job_id,
            "message": "File uploaded successfully and processing started",
            "total_rows": len(employees)
        }
    
    except Exception as e:
        logger.error(f"Error processing upload: {e}")
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/jobs/{job_id}/status")
async def get_job_status(job_id: str):
    async with SessionLocal() as db:
        result = await db.execute(select(ProcessingJob).where(ProcessingJob.id == job_id))
        job = result.scalar_one_or_none()
        
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        result = await db.execute(
            select(ProcessingResult).where(ProcessingResult.job_id == job_id)
        )
        results = result.scalars().all()
        
        success_count = sum(1 for r in results if r.status == "success")
        error_count = sum(1 for r in results if r.status == "error")
        
        return {
            "job_id": job_id,
            "status": job.status,
            "total_rows": job.total_rows,
            "processed_rows": len(results),
            "success_count": success_count,
            "error_count": error_count,
            "created_at": job.created_at,
            "completed_at": job.completed_at,
            "error_message": job.error_message
        }

@app.get("/jobs")
async def list_jobs():
    async with SessionLocal() as db:
        result = await db.execute(select(ProcessingJob).order_by(ProcessingJob.created_at.desc()))
        jobs = result.scalars().all()
        
        return [
            {
                "job_id": job.id,
                "filename": job.filename,
                "status": job.status,
                "total_rows": job.total_rows,
                "created_at": job.created_at,
                "completed_at": job.completed_at
            }
            for job in jobs
        ]

@app.get("/jobs/{job_id}/download")
async def download_results(job_id: str):
    result_file = RESULTS_DIR / f"{job_id}_results.xlsx"
    
    if not result_file.exists():
        raise HTTPException(status_code=404, detail="Results file not found")
    
    return FileResponse(
        path=result_file,
        filename=f"results_{job_id}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str):
    async with SessionLocal() as db:
        result = await db.execute(select(ProcessingJob).where(ProcessingJob.id == job_id))
        job = result.scalar_one_or_none()
        
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        if job.status not in ["failed", "completed", "processing"]:
            raise HTTPException(status_code=400, detail="Job cannot be retried")
        
        # Check if there are any failed results or employees that haven't been processed
        result_query = await db.execute(
            select(ProcessingResult).where(ProcessingResult.job_id == job_id)
        )
        results = result_query.scalars().all()
        
        # Check if there are employees that haven't been processed or have failed
        employee_query = await db.execute(
            select(Employee).where(Employee.job_id == job_id)
        )
        employees = employee_query.scalars().all()
        
        successful_empnos = {r.empno for r in results if r.status == "success"}
        employees_to_retry = [emp for emp in employees if emp.empno not in successful_empnos]
        
        if not employees_to_retry:
            raise HTTPException(status_code=400, detail="All employees have been successfully processed")
        
        logger.info(f"Retrying job {job_id} with {len(employees_to_retry)} employees to process")
        
        # Start retry processing in background
        asyncio.create_task(retry_failed_processing(job_id))
        
        return {
            "job_id": job_id,
            "message": "Job retry initiated",
            "employees_to_retry": len(employees_to_retry)
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)