from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import time
import logging
from contextlib import asynccontextmanager

from app.models import AnalyzeTicketRequest, AnalyzeTicketResponse
from app.services.investigator import TicketInvestigator
from app.utils.safety import validate_safety

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize investigator
investigator = TicketInvestigator(use_llm=False)  # Set to True if using LLM

# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting QueueStorm Investigator API...")
    yield
    # Shutdown
    logger.info("Shutting down...")

# Create FastAPI app
app = FastAPI(
    title="QueueStorm Investigator",
    description="AI/API SupportOps Challenge for Digital Finance",
    version="1.0.0",
    lifespan=lifespan
)

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint - must return within 60 seconds of service start"""
    return {"status": "ok"}

# Main analysis endpoint
@app.post("/analyze-ticket")
async def analyze_ticket(request: AnalyzeTicketRequest):
    """Analyze a support ticket"""
    
    # Validate request
    if not request.ticket_id:
        raise HTTPException(status_code=422, detail="ticket_id is required")
    
    if not request.complaint or len(request.complaint.strip()) == 0:
        raise HTTPException(status_code=422, detail="complaint cannot be empty")
    
    try:
        # Process ticket
        start_time = time.time()
        
        response = investigator.investigate(request)
        
        # Log processing time
        elapsed = time.time() - start_time
        logger.info(f"Processed ticket {request.ticket_id} in {elapsed:.2f}s")
        
        # Ensure response is within 30 second limit
        if elapsed > 30:
            logger.warning(f"Response time exceeded 30 seconds: {elapsed:.2f}s")
        
        return response
        
    except Exception as e:
        logger.error(f"Error processing ticket {request.ticket_id}: {str(e)}")
        # Return 500 without exposing stack trace
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred while processing your request."
        )

# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions with proper error messages"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

# Optional: Root endpoint
@app.get("/")
async def root():
    return {
        "service": "QueueStorm Investigator",
        "endpoints": {
            "health": "/health",
            "analyze": "/analyze-ticket (POST)"
        },
        "version": "1.0.0"
    }