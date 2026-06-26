import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # LLM Configuration (optional)
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "")  # "openai", "anthropic", or ""
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    
    # Service Configuration
    USE_LLM = bool(LLM_PROVIDER)
    REQUEST_TIMEOUT = 30  # seconds
    
    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")