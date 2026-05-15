import asyncio
import httpx
from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

async def send_otp_email(to_email: str, otp_code: str):
    """
    Sends a 6-digit OTP to the specified email address using the Resend REST API.
    This bypasses Render's SMTP block on ports 465/587 by using HTTPS (port 443).
    """
    subject = "Your SACH Citizen Portal Verification Code"
    
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
        <div style="max-width: 500px; margin: 0 auto; background-color: #ffffff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); text-align: center;">
          <h2 style="color: #01763A; margin-bottom: 20px;">SACH Citizen Portal</h2>
          <p style="color: #333333; font-size: 16px; line-height: 1.5;">You have requested to securely log in using an Email OTP.</p>
          <p style="color: #333333; font-size: 16px; margin-bottom: 30px;">Here is your 6-digit verification code:</p>
          
          <div style="background-color: #f9f9f9; padding: 15px; border-radius: 6px; border: 1px solid #e0e0e0; display: inline-block;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 6px; color: #D4AF37;">{otp_code}</span>
          </div>
          
          <p style="color: #666666; font-size: 13px; margin-top: 30px;">This code will expire in <strong>5 minutes</strong>. If you did not request this, please ignore this email.</p>
        </div>
      </body>
    </html>
    """

    if not settings.RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not configured. Email not sent.")
        logger.info(f"[DEV MODE] Email to {to_email} | Subject: {subject} | Content: {otp_code}")
        return

    # For testing on Resend without a verified domain, you MUST use onboarding@resend.dev
    # We will use the custom domain if SMTP_FROM_EMAIL is set, but otherwise default to onboarding
    from_email = settings.SMTP_FROM_EMAIL if settings.SMTP_FROM_EMAIL and "gmail.com" not in settings.SMTP_FROM_EMAIL else "onboarding@resend.dev"
    
    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "from": f"SACH Citizen Portal <{from_email}>",
        "to": [to_email],
        "subject": subject,
        "html": html_content
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://api.resend.com/emails", json=payload, headers=headers, timeout=10.0)
            
            if response.status_code >= 400:
                logger.error(f"Resend API error: {response.status_code} - {response.text}")
                response.raise_for_status()
                
            logger.info(f"Email successfully sent to {to_email} via Resend")
    except Exception as e:
        logger.error(f"Failed to send email to {to_email} via Resend: {str(e)}")
        raise
