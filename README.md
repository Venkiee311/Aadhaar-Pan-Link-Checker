# Aadhar Processing System

A FastAPI-based web application for processing Excel files containing employee data and validating Aadhar information through the Income Tax Portal API.

## Features

- **File Upload**: Upload Excel files with employee data (EMPNO, EMPLOYEE NAME, PAN NO, Aadhar NO)
- **Async Processing**: Background processing with rate limiting and retry mechanisms
- **Status Tracking**: Real-time status monitoring with progress indicators
- **Database Storage**: SQLite database for storing job status, results, and API responses
- **Rate Limiting**: Respects API rate limits with exponential backoff (30 requests/minute, max 3 concurrent)
- **Retry Logic**: Automatic retries for failed API calls (up to 3 retries with exponential backoff)
- **Result Download**: Download processed results as Excel files with separate sheets for successes and errors
- **Web Interface**: Clean HTML interface for upload and monitoring
- **Job Management**: View all jobs, retry failed/incomplete jobs, and track processing progress

## Setup

1. Install dependencies using uv:
```bash
uv sync
```

2. Run the application:
```bash
uv run python main.py
```

3. Open your browser and go to `http://localhost:8000`

## Usage

1. **Upload Excel File**: 
   - Go to the home page
   - Upload an Excel file with the required columns
   - Specify the sheet name (default: "Sheet1")

2. **Monitor Progress**:
   - Visit the Status page to see all jobs
   - View detailed progress for each job
   - Real-time updates every 5 seconds

3. **Download Results**:
   - Once processing is complete, download the results
   - Results include both successful API responses and errors

## Excel File Format

Your Excel file must contain the following columns:
- `EMPNO`: Employee number
- `EMPLOYEE NAME`: Employee name
- `PAN NO`: PAN number
- `Aadhar NO`: Aadhar number

## API Configuration

The system interacts with the Income Tax Portal API (`https://eportal.incometax.gov.in/iec/servicesapi/getEntity`) with the following limits:
- **Rate Limiting**: Maximum 30 requests per minute
- **Concurrency**: Maximum 3 concurrent requests
- **Retry Strategy**: Up to 3 retries with exponential backoff for failed requests
- **Timeout**: 30 seconds per API request

## Database Schema

The system uses SQLite with the following tables:
- `processing_jobs`: Job metadata and status (id, filename, status, total_rows, created_at, completed_at, error_message)
- `employees`: Employee data from uploaded files (empno, employee_name, pan_no, aadhar_no)
- `processing_results`: API responses and processing results (empno, status, api_response, error_message, retry_count)

## File Structure

```
├── app.py              # FastAPI application with all API endpoints
├── main.py             # Application runner (entry point)
├── database.py         # Database configuration and setup
├── models.py           # SQLAlchemy models (ProcessingJob, Employee, ProcessingResult)
├── tasks.py            # Background processing tasks and API calls
├── utils.py            # Utility functions for Excel reading and validation
├── templates/          # HTML templates
│   ├── base.html       # Base template
│   ├── upload.html     # File upload interface
│   └── status.html     # Job status monitoring
├── uploads/            # Uploaded Excel files (auto-created)
├── results/            # Generated result files (auto-created)
├── pyproject.toml      # Project dependencies and configuration
└── requirements.txt    # Compiled dependencies (uv generated)
```

## API Endpoints

- `GET /` - Upload form interface
- `GET /status` - Job status monitoring page
- `POST /upload` - Upload Excel file and start processing
- `GET /jobs` - List all processing jobs
- `GET /jobs/{job_id}/status` - Get detailed job status
- `GET /jobs/{job_id}/download` - Download results Excel file
- `POST /jobs/{job_id}/retry` - Retry failed or incomplete jobs

## Dependencies

Key Python packages used:
- **FastAPI**: Web framework for the API
- **SQLAlchemy**: Database ORM with async support
- **aiosqlite**: Async SQLite driver
- **openpyxl**: Excel file reading and writing
- **aiohttp**: Async HTTP client for API calls
- **asyncio-throttle**: Rate limiting for API requests
- **Pydantic**: Data validation and serialization
- **Jinja2**: HTML templating
- **uvicorn**: ASGI server
