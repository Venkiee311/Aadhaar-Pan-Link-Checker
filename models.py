from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from database import Base


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id = Column(String, primary_key=True)
    filename = Column(String, nullable=False)
    sheet_name = Column(String, nullable=False)
    total_rows = Column(Integer, nullable=False)
    status = Column(
        String, nullable=False, default="queued"
    )  # queued, processing, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    error_message = Column(Text)

    employees = relationship("Employee", back_populates="job", cascade="all, delete-orphan")
    results = relationship("ProcessingResult", back_populates="job", cascade="all, delete-orphan")


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("processing_jobs.id"), nullable=False)
    empno = Column(Integer, nullable=False)
    employee_name = Column(String, nullable=False)
    pan_no = Column(String, nullable=False)
    aadhar_no = Column(String, nullable=False)

    job = relationship("ProcessingJob", back_populates="employees")


class ProcessingResult(Base):
    __tablename__ = "processing_results"
    __table_args__ = (UniqueConstraint('job_id', 'empno', name='_job_empno_uc'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("processing_jobs.id"), nullable=False)
    empno = Column(Integer, nullable=False)
    employee_name = Column(String, nullable=False)
    pan_no = Column(String, nullable=False)
    aadhar_no = Column(String, nullable=False)
    status = Column(String, nullable=False)  # success, error
    api_response = Column(Text)
    error_message = Column(Text)
    error_code = Column(String)
    status_code = Column(Integer)
    processed_at = Column(DateTime, default=datetime.utcnow)
    retry_count = Column(Integer, default=0)

    job = relationship("ProcessingJob", back_populates="results")
