from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/preview", response_class=HTMLResponse)
def get_user_preview():
    return """
    <div style="background-color: #21262d; border: 1px solid #30363d; border-radius: 6px; padding: 12px; margin-top: 10px;">
        <h3 style="margin: 0 0 6px 0; color: #58a6ff;">API Connection Verified!</h3>
        <p style="margin: 0; color: #8b949e; font-size: 14px;">
            This raw HTML was generated directly by the FastAPI backend endpoint.
        </p>
        <span style="display: inline-block; margin-top: 8px; font-size: 12px; color: #3fb950; font-weight: bold;">
            ✓ Status: 200 OK
        </span>
    </div>
    """