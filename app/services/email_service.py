import smtplib
import asyncio
from email.message import EmailMessage
from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

def _send_email_sync(to_email: str, subject: str, html_content: str):
    if not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
        logger.warning("SMTP credentials not configured. Email not sent.")
        # Print OTP to log for local development if email isn't configured
        logger.info(f"[DEV MODE] Email to {to_email} | Subject: {subject} | Content: {html_content}")
        return

    try:
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = settings.SMTP_FROM_EMAIL
        msg['To'] = to_email
        msg.set_content(html_content, subtype='html')

        with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.send_message(msg)
            
        logger.info(f"Email successfully sent to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        raise

async def send_otp_email(to_email: str, otp_code: str):
    """
    Sends a 6-digit OTP to the specified email address using an HTML template.
    Runs asynchronously using a threadpool to prevent blocking the event loop.
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
    
    # Run the blocking SMTP call in a separate thread
    await asyncio.to_thread(_send_email_sync, to_email, subject, html_content)
