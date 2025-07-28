import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import aiohttp
import openpyxl
from asyncio_throttle import Throttler
from openpyxl.workbook import Workbook
from pydantic import BaseModel, ValidationError
from sqlalchemy import select, update

from database import SessionLocal
from models import Employee, ProcessingJob, ProcessingResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "https://eportal.incometax.gov.in/iec/servicesapi/getEntity"
MAX_CONCURRENT_REQUESTS = 3
RATE_LIMIT_PER_MINUTE = 30
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

class APIResponseMessage(BaseModel):
    code: str
    type: str
    desc: str
    fieldName: Optional[str] = None

class APIResponse(BaseModel):
    messages: List[APIResponseMessage] = []
    errors: List[dict] = []
    aadhaarNumber: str = ""
    pan: str = ""

async def call_api_with_session(session: aiohttp.ClientSession, pan: str, aadhar: str) -> Tuple[Optional[APIResponse], Optional[str], Optional[int]]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-IN,en-US;q=0.9,en-GB;q=0.8,en;q=0.7,hi;q=0.6",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Content-Type": "application/json",
        "Origin": "https://eportal.incometax.gov.in",
        "Pragma": "no-cache",
        "Referer": "https://eportal.incometax.gov.in/iec/foservices/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Linux"',
        "sn": "linkAadhaarPreLoginService",
    }

    data = {
        "aadhaarNumber": aadhar,
        "pan": pan,
        "preLoginFlag": "Y",
        "serviceName": "linkAadhaarPreLoginService",
    }

    try:
        async with session.post(API_URL, headers=headers, json=data, timeout=30) as response:
            status_code = response.status
            response_text = await response.text()
            
            if response.status == 429:  # Rate limited
                return None, "Rate limited", status_code
            
            response.raise_for_status()
            response_json = await response.json()
            return APIResponse(**response_json), None, status_code
            
    except asyncio.TimeoutError:
        return None, "Request timeout", None
    except aiohttp.ClientError as e:
        return None, f"Client error: {str(e)}", getattr(e, 'status', None)
    except ValidationError as e:
        return None, f"Response validation error: {str(e)}", None
    except Exception as e:
        return None, f"Unexpected error: {str(e)}", None

async def process_employee_with_retries(
    session: aiohttp.ClientSession,
    throttler: Throttler,
    employee: Employee,
    job_id: str
) -> None:
    retry_count = 0
    
    while retry_count <= MAX_RETRIES:
        try:
            async with throttler:
                logger.info(f"Processing employee {employee.employee_name} (attempt {retry_count + 1})")
                
                api_response, error_message, status_code = await call_api_with_session(
                    session, str(employee.pan_no), str(employee.aadhar_no)
                )
                
                # Handle rate limiting
                if status_code == 429:
                    retry_count += 1
                    if retry_count <= MAX_RETRIES:
                        wait_time = RETRY_DELAY * (2 ** retry_count)  # Exponential backoff
                        logger.warning(f"Rate limited for {employee.employee_name}, retrying in {wait_time}s")
                        await asyncio.sleep(wait_time)
                        continue
                
                # Save result to database
                async with SessionLocal() as db:
                    if api_response and api_response.messages:
                        message = api_response.messages[0]
                        if message.type == "ERROR":
                            result = ProcessingResult(
                                job_id=job_id,
                                empno=employee.empno,
                                employee_name=employee.employee_name,
                                pan_no=employee.pan_no,
                                aadhar_no=employee.aadhar_no,
                                status="error",
                                error_message=message.desc,
                                error_code=message.code,
                                status_code=status_code,
                                retry_count=retry_count,
                                api_response=json.dumps(api_response.model_dump(), indent=2) if api_response else None
                            )
                        else:
                            result = ProcessingResult(
                                job_id=job_id,
                                empno=employee.empno,
                                employee_name=employee.employee_name,
                                pan_no=employee.pan_no,
                                aadhar_no=employee.aadhar_no,
                                status="success",
                                api_response=json.dumps(api_response.model_dump(), indent=2),
                                status_code=status_code,
                                retry_count=retry_count
                            )
                    else:
                        result = ProcessingResult(
                            job_id=job_id,
                            empno=employee.empno,
                            employee_name=employee.employee_name,
                            pan_no=employee.pan_no,
                            aadhar_no=employee.aadhar_no,
                            status="error",
                            error_message=error_message or "No valid response from API",
                            status_code=status_code,
                            retry_count=retry_count
                        )
                    
                    db.add(result)
                    await db.commit()
                    
                return  # Success, exit retry loop
                
        except Exception as e:
            retry_count += 1
            logger.error(f"Error processing {employee.employee_name} (attempt {retry_count}): {e}")
            
            if retry_count <= MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * retry_count)
            else:
                # Final failure - save error to database
                async with SessionLocal() as db:
                    result = ProcessingResult(
                        job_id=job_id,
                        empno=employee.empno,
                        employee_name=employee.employee_name,
                        pan_no=employee.pan_no,
                        aadhar_no=employee.aadhar_no,
                        status="error",
                        error_message=f"Failed after {MAX_RETRIES} retries: {str(e)}",
                        retry_count=retry_count - 1
                    )
                    db.add(result)
                    await db.commit()

async def create_output_excel(job_id: str) -> None:
    async with SessionLocal() as db:
        result = await db.execute(
            select(ProcessingResult).where(ProcessingResult.job_id == job_id)
        )
        results = result.scalars().all()
        
        if not results:
            logger.warning(f"No results found for job {job_id}")
            return
        
        workbook = Workbook()
        
        # Success sheet
        success_sheet = workbook.active
        success_sheet.title = "API_Responses"
        success_sheet.append(
            ["EMPNO", "EMPLOYEE NAME", "PAN NO", "Aadhar NO", "Message", "Code", "Type"]
        )
        
        error_records = []
        
        for result in results:
            if result.status == "success":
                # Extract message details from API response
                message_desc = ""
                message_code = ""
                message_type = ""
                
                if result.api_response:
                    try:
                        api_data = json.loads(result.api_response)
                        if api_data.get("messages") and len(api_data["messages"]) > 0:
                            first_message = api_data["messages"][0]
                            message_desc = first_message.get("desc", "")
                            message_code = first_message.get("code", "")
                            message_type = first_message.get("type", "")
                    except json.JSONDecodeError:
                        message_desc = "Unable to parse API response"
                
                success_sheet.append([
                    result.empno,
                    result.employee_name,
                    result.pan_no,
                    result.aadhar_no,
                    message_desc,
                    message_code,
                    message_type
                ])
            else:
                error_records.append([
                    result.empno,
                    result.employee_name,
                    result.pan_no,
                    result.aadhar_no,
                    result.error_message or "",
                    result.error_code or "",
                    result.status_code or ""
                ])
        
        # Error sheet
        if error_records:
            error_sheet = workbook.create_sheet(title="Errors")
            error_sheet.append([
                "EMPNO", "EMPLOYEE NAME", "PAN NO", "Aadhar NO", 
                "Error Message", "Error Code", "Status Code"
            ])
            for record in error_records:
                error_sheet.append(record)
        
        # Save file
        results_dir = Path("results")
        results_dir.mkdir(exist_ok=True)
        output_path = results_dir / f"{job_id}_results.xlsx"
        
        workbook.save(output_path)
        logger.info(f"Results saved to {output_path}")

async def process_excel_task(job_id: str, file_path: str, sheet_name: str) -> None:
    try:
        # Update job status to processing
        async with SessionLocal() as db:
            await db.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_id)
                .values(status="processing")
            )
            await db.commit()
        
        # Get employees from database
        async with SessionLocal() as db:
            result = await db.execute(
                select(Employee).where(Employee.job_id == job_id)
            )
            employees = result.scalars().all()
        
        if not employees:
            raise ValueError("No employees found for this job")
        
        # Create throttler for rate limiting
        throttler = Throttler(rate_limit=RATE_LIMIT_PER_MINUTE, period=60)
        
        # Process employees with limited concurrency
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        
        async def process_with_semaphore(employee):
            async with semaphore:
                async with aiohttp.ClientSession() as session:
                    await process_employee_with_retries(session, throttler, employee, job_id)
        
        # Process all employees
        tasks = [process_with_semaphore(emp) for emp in employees]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Create output Excel file
        await create_output_excel(job_id)
        
        # Update job status to completed
        async with SessionLocal() as db:
            await db.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_id)
                .values(status="completed", completed_at=datetime.utcnow())
            )
            await db.commit()
        
        logger.info(f"Job {job_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        
        # Update job status to failed
        async with SessionLocal() as db:
            await db.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_id)
                .values(status="failed", error_message=str(e), completed_at=datetime.utcnow())
            )
            await db.commit()

async def retry_failed_processing(job_id: str) -> None:
    """
    Retry processing for a failed or incomplete job.
    Only processes employees that don't have successful results or have errors.
    """
    try:
        logger.info(f"Starting retry process for job {job_id}")
        
        # Update job status to processing
        async with SessionLocal() as db:
            await db.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_id)
                .values(status="processing", error_message=None)
            )
            await db.commit()
        
        # Get employees that need to be reprocessed
        async with SessionLocal() as db:
            # Get all employees for this job
            employee_result = await db.execute(
                select(Employee).where(Employee.job_id == job_id)
            )
            all_employees = employee_result.scalars().all()
            
            # Get successful results
            success_result = await db.execute(
                select(ProcessingResult.empno)
                .where(ProcessingResult.job_id == job_id)
                .where(ProcessingResult.status == "success")
            )
            successful_empnos = {row[0] for row in success_result.fetchall()}
            
            # Filter employees that need reprocessing
            employees_to_process = [
                emp for emp in all_employees 
                if emp.empno not in successful_empnos
            ]
        
        if not employees_to_process:
            logger.info(f"No employees need reprocessing for job {job_id}")
            
            # Update job status to completed
            async with SessionLocal() as db:
                await db.execute(
                    update(ProcessingJob)
                    .where(ProcessingJob.id == job_id)
                    .values(status="completed", completed_at=datetime.utcnow())
                )
                await db.commit()
            return
        
        logger.info(f"Reprocessing {len(employees_to_process)} employees for job {job_id}")
        
        # Delete existing error results for employees being reprocessed
        async with SessionLocal() as db:
            empnos_to_reprocess = [emp.empno for emp in employees_to_process]
            
            from sqlalchemy import delete
            await db.execute(
                delete(ProcessingResult)
                .where(ProcessingResult.job_id == job_id)
                .where(ProcessingResult.empno.in_(empnos_to_reprocess))
                .where(ProcessingResult.status == "error")
            )
            await db.commit()
        
        # Create throttler for rate limiting
        throttler = Throttler(rate_limit=RATE_LIMIT_PER_MINUTE, period=60)
        
        # Process employees with limited concurrency
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        
        async def process_with_semaphore(employee):
            async with semaphore:
                async with aiohttp.ClientSession() as session:
                    await process_employee_with_retries(session, throttler, employee, job_id)
        
        # Process employees that need reprocessing
        tasks = [process_with_semaphore(emp) for emp in employees_to_process]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Create updated output Excel file
        await create_output_excel(job_id)
        
        # Update job status to completed
        async with SessionLocal() as db:
            await db.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_id)
                .values(status="completed", completed_at=datetime.utcnow())
            )
            await db.commit()
        
        logger.info(f"Retry processing for job {job_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Retry processing for job {job_id} failed: {e}")
        
        # Update job status to failed
        async with SessionLocal() as db:
            await db.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_id)
                .values(status="failed", error_message=f"Retry failed: {str(e)}", completed_at=datetime.utcnow())
            )
            await db.commit()