"""
Cloud Telegram Bot for JARVIS Hybrid Architecture

This bot runs 24/7 in the cloud and:
1. Handles chat/information requests directly via Gemini API
2. Forwards PC action requests to local JARVIS when online
3. Responds gracefully when local JARVIS is offline
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

class Config:
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")  # Your user ID for authorization
    
    # Gemini
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = "gemini-1.5-flash"
    
    # Cloud Bot
    CLOUD_BOT_PORT: int = int(os.getenv("PORT", "8000"))
    CLOUD_BOT_HOST: str = "0.0.0.0"
    
    # Local JARVIS registration
    LOCAL_JARVIS_TIMEOUT: int = 30  # seconds to wait for local response
    HEARTBEAT_INTERVAL: int = 30    # seconds between heartbeats
    LOCAL_JARVIS_MAX_AGE: int = 60  # seconds before considering local offline

config = Config()

# =============================================================================
# Data Models
# =============================================================================

@dataclass
class LocalJarvisInstance:
    """Represents a connected local JARVIS instance."""
    instance_id: str
    endpoint: str  # e.g., "https://xxx.ngrok-free.app" or local IP
    capabilities: list[str] = field(default_factory=list)
    last_heartbeat: datetime = field(default_factory=datetime.now)
    registered_at: datetime = field(default_factory=datetime.now)
    
    def is_online(self) -> bool:
        age = (datetime.now() - self.last_heartbeat).total_seconds()
        return age < config.LOCAL_JARVIS_MAX_AGE
    
    def update_heartbeat(self):
        self.last_heartbeat = datetime.now()

# Global state
local_instances: Dict[str, LocalJarvisInstance] = {}
gemini_model = None
telegram_bot: Optional[Bot] = None

# =============================================================================
# Pydantic Models for API
# =============================================================================

class RegisterRequest(BaseModel):
    instance_id: str
    endpoint: str
    capabilities: list[str] = []

class HeartbeatRequest(BaseModel):
    instance_id: str

class ActionRequest(BaseModel):
    action: str
    parameters: dict = {}

class ActionResponse(BaseModel):
    success: bool
    result: Any = None
    error: str = ""

# =============================================================================
# Gemini Integration
# =============================================================================

def init_gemini():
    global gemini_model
    if config.GEMINI_API_KEY:
        genai.configure(api_key=config.GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel(config.GEMINI_MODEL)
        logger.info("Gemini initialized")
    else:
        logger.warning("GEMINI_API_KEY not set - chat will not work")

async def gemini_chat(prompt: str, system_prompt: str = "") -> str:
    """Get response from Gemini."""
    if not gemini_model:
        return "Gemini not configured. Please set GEMINI_API_KEY."
    
    try:
        full_prompt = f"{system_prompt}\n\nUser: {prompt}" if system_prompt else prompt
        response = await asyncio.to_thread(gemini_model.generate_content, full_prompt)
        return response.text or "No response from Gemini."
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return f"Error: {str(e)}"

# =============================================================================
# Local JARVIS Communication
# =============================================================================

async def forward_to_local(instance: LocalJarvisInstance, action: str, parameters: dict) -> ActionResponse:
    """Forward action request to local JARVIS instance."""
    url = f"{instance.endpoint.rstrip('/')}/api/jarvis/action"
    
    try:
        async with httpx.AsyncClient(timeout=config.LOCAL_JARVIS_TIMEOUT) as client:
            response = await client.post(url, json={
                "action": action,
                "parameters": parameters
            })
            response.raise_for_status()
            data = response.json()
            return ActionResponse(**data)
    except httpx.TimeoutException:
        return ActionResponse(success=False, error="Local JARVIS timeout")
    except httpx.ConnectError:
        return ActionResponse(success=False, error="Cannot connect to local JARVIS")
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

def get_online_instance() -> Optional[LocalJarvisInstance]:
    """Get the first online local JARVIS instance."""
    for instance in local_instances.values():
        if instance.is_online():
            return instance
    return None

# =============================================================================
# Telegram Bot Handlers
# =============================================================================

SYSTEM_PROMPT = """You are JARVIS, an AI assistant. You can chat naturally and provide information.
When the user asks for PC actions (screenshot, system status, file operations, etc.), 
you should explain that you'll forward the request to their local JARVIS instance.
If local JARVIS is offline, inform them that PC actions require their computer to be on."""

ACTION_KEYWORDS = {
    "screenshot": ["screenshot", "screen capture", "capture screen", "show my screen"],
    "system_status": ["system status", "pc status", "computer status", "system info", "cpu", "ram", "temperature"],
    "file_operation": ["file", "folder", "directory", "open file", "read file", "write file"],
    "app_control": ["open app", "close app", "launch", "run program"],
    "web_search": ["search", "google", "look up", "find information"],
    "camera": ["camera", "webcam", "take photo"],
}

def detect_action_intent(text: str) -> Optional[str]:
    """Detect if user wants a PC action."""
    text_lower = text.lower()
    for action, keywords in ACTION_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return action
    return None

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if not is_authorized(update):
        return
    
    instance = get_online_instance()
    status = "🟢 Online" if instance else "🔴 Offline"
    
    await update.message.reply_text(
        f"🤖 JARVIS Cloud Bot\n\n"
        f"Local JARVIS: {status}\n\n"
        f"Commands:\n"
        f"• /status - Check local JARVIS status\n"
        f"• /screenshot - Capture screen (requires local JARVIS)\n"
        f"• /pc - Get system status (requires local JARVIS)\n"
        f"• Just chat naturally for questions/info!\n\n"
        f"When your PC is on and JARVIS is running, I can control it.\n"
        f"When your PC is off, I still work as a chat bot."
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command."""
    if not is_authorized(update):
        return
    
    instance = get_online_instance()
    if instance:
        await update.message.reply_text(
            f"🟢 Local JARVIS is ONLINE\n"
            f"Instance: {instance.instance_id}\n"
            f"Endpoint: {instance.endpoint}\n"
            f"Capabilities: {', '.join(instance.capabilities) or 'None'}\n"
            f"Last heartbeat: {instance.last_heartbeat.strftime('%H:%M:%S')}"
        )
    else:
        await update.message.reply_text(
            "🔴 Local JARVIS is OFFLINE\n"
            "Your PC appears to be off or JARVIS isn't running.\n"
            "I can still chat and answer questions!"
        )

async def screenshot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /screenshot command."""
    if not is_authorized(update):
        return
    
    instance = get_online_instance()
    if not instance:
        await update.message.reply_text("🔴 Local JARVIS is offline. Cannot capture screenshot.")
        return
    
    await update.message.reply_text("📸 Capturing screenshot...")
    result = await forward_to_local(instance, "screenshot", {})
    
    if result.success:
        await update.message.reply_text("✅ Screenshot captured and sent!")
    else:
        await update.message.reply_text(f"❌ Failed: {result.error}")

async def pc_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pc command."""
    if not is_authorized(update):
        return
    
    instance = get_online_instance()
    if not instance:
        await update.message.reply_text("🔴 Local JARVIS is offline. Cannot get system status.")
        return
    
    await update.message.reply_text("📊 Getting system status...")
    result = await forward_to_local(instance, "system_status", {})
    
    if result.success:
        await update.message.reply_text(f"📊 System Status:\n{result.result}")
    else:
        await update.message.reply_text(f"❌ Failed: {result.error}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular chat messages."""
    if not is_authorized(update):
        return
    
    text = update.message.text
    if not text:
        return
    
    # Check for action intent
    action = detect_action_intent(text)
    instance = get_online_instance()
    
    if action and instance:
        # Forward to local JARVIS
        await update.message.reply_text(f"🔄 Forwarding to local JARVIS ({action})...")
        result = await forward_to_local(instance, action, {"query": text})
        
        if result.success:
            await update.message.reply_text(f"✅ Done: {result.result}")
        else:
            await update.message.reply_text(f"❌ Failed: {result.error}")
            # Fall back to chat
            response = await gemini_chat(text, SYSTEM_PROMPT)
            await update.message.reply_text(response)
    elif action and not instance:
        # Local offline - explain limitation
        await update.message.reply_text(
            f"🔴 Local JARVIS is offline, so I can't {action.replace('_', ' ')}.\n"
            f"Turn on your PC and start JARVIS for PC control.\n\n"
            f"But I can still chat! What would you like to know?"
        )
    else:
        # Regular chat
        response = await gemini_chat(text, SYSTEM_PROMPT)
        await update.message.reply_text(response)

def is_authorized(update: Update) -> bool:
    """Check if user is authorized."""
    if not config.TELEGRAM_CHAT_ID:
        return True  # No restriction if not configured
    return str(update.effective_chat.id) == config.TELEGRAM_CHAT_ID

# =============================================================================
# FastAPI App for Local JARVIS Registration
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_gemini()
    logger.info("Cloud bot starting up...")
    yield
    # Shutdown
    logger.info("Cloud bot shutting down...")

app = FastAPI(title="JARVIS Cloud Bot", lifespan=lifespan)

@app.post("/api/register")
async def register_local(request: RegisterRequest):
    """Register a local JARVIS instance."""
    instance = LocalJarvisInstance(
        instance_id=request.instance_id,
        endpoint=request.endpoint,
        capabilities=request.capabilities
    )
    local_instances[request.instance_id] = instance
    logger.info(f"Local JARVIS registered: {request.instance_id} at {request.endpoint}")
    return {"status": "registered", "instance_id": request.instance_id}

@app.post("/api/heartbeat")
async def heartbeat(request: HeartbeatRequest):
    """Receive heartbeat from local JARVIS."""
    if request.instance_id in local_instances:
        local_instances[request.instance_id].update_heartbeat()
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Instance not registered")

@app.post("/api/unregister")
async def unregister_local(request: RegisterRequest):
    """Unregister a local JARVIS instance."""
    if request.instance_id in local_instances:
        del local_instances[request.instance_id]
        logger.info(f"Local JARVIS unregistered: {request.instance_id}")
    return {"status": "unregistered"}

@app.get("/api/instances")
async def list_instances():
    """List all registered instances."""
    return {
        "instances": [
            {
                "instance_id": inst.instance_id,
                "endpoint": inst.endpoint,
                "capabilities": inst.capabilities,
                "online": inst.is_online(),
                "last_heartbeat": inst.last_heartbeat.isoformat()
            }
            for inst in local_instances.values()
        ]
    }

# =============================================================================
# Main Entry Point
# =============================================================================

async def run_telegram_bot():
    """Run the Telegram bot."""
    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return
    
    global telegram_bot
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    telegram_bot = application.bot
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("screenshot", screenshot_command))
    application.add_handler(CommandHandler("pc", pc_status_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start polling
    logger.info("Starting Telegram bot polling...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

async def run_fastapi():
    """Run FastAPI server."""
    import uvicorn
    config_uvicorn = uvicorn.Config(app, host=config.CLOUD_BOT_HOST, port=config.CLOUD_BOT_PORT, log_level="info")
    server = uvicorn.Server(config_uvicorn)
    await server.serve()

async def main():
    """Run both Telegram bot and FastAPI server."""
    await asyncio.gather(
        run_telegram_bot(),
        run_fastapi(),
    )

if __name__ == "__main__":
    asyncio.run(main())