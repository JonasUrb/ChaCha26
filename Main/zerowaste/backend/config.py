import os
from dotenv import load_dotenv

load_dotenv()

ACADEMIC_CLOUD_API_KEY = os.getenv("ACADEMIC_CLOUD_API_KEY")
ACADEMIC_CLOUD_BASE_URL = os.getenv(
    "ACADEMIC_CLOUD_BASE_URL",
    "https://chat-ai.academiccloud.de/v1"
)
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3-omni-30b-a3b-instruct")

if not ACADEMIC_CLOUD_API_KEY:
    raise RuntimeError(
        "ACADEMIC_CLOUD_API_KEY is missing. Please set it in your .env file."
    )