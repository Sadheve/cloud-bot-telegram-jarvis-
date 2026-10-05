# JARVIS Cloud Bot - Hybrid Telegram Control

This enables **hybrid Telegram control** for JARVIS:
- **PC ON + JARVIS running** → Full PC control (screenshots, system status, file ops, etc.)
- **PC OFF / JARVIS not running** → Chat/Information bot still works via Gemini API

## Architecture

```
┌─────────────┐     HTTPS      ┌──────────────────┐     Local API      ┌─────────────────┐
│  Telegram   │ ◀────────────▶ │   Cloud Bot      │ ◀────────────────▶ │  Local JARVIS   │
│   (You)     │                │  (Always Online) │   (via ngrok)      │  (When PC On)   │
└─────────────┘                └──────────────────┘                    └─────────────────┘
                                      │
                                      ▼
                              ┌──────────────────┐
                              │   Gemini API     │
                              │  (Chat/Info)     │
                              └──────────────────┘
```

## Quick Deploy to Railway (Recommended)

1. **Fork/Clone this repo** to your GitHub

2. **Create Railway project:**
   - Go to [railway.app](https://railway.app)
   - New Project → Deploy from GitHub repo
   - Select this repository / `cloud_bot` folder

3. **Set Environment Variables in Railway:**
   ```
   TELEGRAM_BOT_TOKEN=your_bot_token_from_BotFather
   TELEGRAM_CHAT_ID=your_telegram_user_id
   GEMINI_API_KEY=your_gemini_api_key
   ```

4. **Deploy!** Railway gives you a URL like `https://jarvis-cloud-bot.railway.app`

## Alternative: Deploy to Render / Fly.io / VPS

### Render
1. New Web Service → Connect GitHub
2. Build: `pip install -r requirements.txt`
3. Start: `python main.py`
4. Add environment variables

### Fly.io
```bash
fly launch --name jarvis-cloud-bot --dockerfile Dockerfile
fly secrets set TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=xxx GEMINI_API_KEY=xxx
fly deploy
```

### VPS (Docker)
```bash
docker build -t jarvis-cloud-bot .
docker run -d \
  -e TELEGRAM_BOT_TOKEN=xxx \
  -e TELEGRAM_CHAT_ID=xxx \
  -e GEMINI_API_KEY=xxx \
  -p 8000:8000 \
  --restart unless-stopped \
  jarvis-cloud-bot
```

## Local JARVIS Setup

### 1. Configure Cloud Bot URL
Edit `config/api_keys.json`:
```json
{
  "gemini_api_key": "your_key",
  "telegram_bot_token": "your_token",
  "telegram_chat_id": "your_id",
  "cloud_bot_url": "https://your-cloud-bot.railway.app",
  "cloud_bot_token": "optional_shared_secret",
  "cloud_instance_id": "my-pc-01"
}
```

### 2. Set up ngrok Tunnel (for cloud → local communication)
```bash
# Install ngrok
winget install ngrok  # Windows
# or download from ngrok.com

# Authenticate
ngrok config add-authtoken YOUR_NGROK_TOKEN

# Run the setup script
python cloud_bot/setup_ngrok.py
```

This creates a public HTTPS URL (e.g., `https://abc123.ngrok-free.app`) and saves it to config.

### 3. Start Cloud Connector in JARVIS
In JARVIS chat or command:
```
cloud_connector action=start
```

Or it auto-starts on JARVIS launch if configured.

## Usage

### When PC is ON (JARVIS running):
- `/start` - Shows status
- `/status` - Check local JARVIS connection
- `/screenshot` - Capture and send screenshot
- `/pc` - Get system status (CPU, RAM, temp)
- "Take a screenshot" - Natural language → forwards to local
- "What's my CPU usage?" - Forwards to local
- Regular chat → Answers via Gemini

### When PC is OFF (JARVIS not running):
- `/start` - Shows "Local JARVIS offline"
- `/screenshot` - "Local JARVIS offline, cannot capture"
- Regular chat → **Still works!** Answers via Gemini API

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message + status |
| `/status` | Check local JARVIS connection |
| `/screenshot` | Capture screen (needs local) |
| `/pc` | System status (needs local) |
| Natural language | Chat + auto-detects PC actions |

## Configuration Options

### Cloud Bot (Environment Variables)
| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | From @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | Your user ID from @userinfobot |
| `GEMINI_API_KEY` | Yes | From Google AI Studio |
| `PORT` | No | Port (auto-set by platform) |

### Local JARVIS (config/api_keys.json)
| Key | Required | Description |
|-----|----------|-------------|
| `cloud_bot_url` | Yes | Cloud bot URL (e.g., https://xxx.railway.app) |
| `cloud_bot_token` | No | Shared secret for auth |
| `cloud_instance_id` | No | Unique ID for this PC |
| `cloud_public_url` | Yes* | ngrok tunnel URL (auto-set by setup script) |

*Required for cloud→local communication

## How It Works

1. **Cloud bot starts** → Listens for Telegram messages + serves API
2. **Local JARVIS starts** → Registers with cloud bot via `/api/register`
3. **Heartbeats** → Local sends heartbeat every 30s to `/api/heartbeat`
4. **You message bot** → Cloud bot receives via Telegram webhook/polling
5. **Chat/Info** → Cloud bot answers directly via Gemini
6. **PC Action** → Cloud bot forwards to local via ngrok → Local executes → Returns result
7. **Local JARVIS stops** → Sends `/api/unregister` → Cloud marks offline

## Security

- **Authorization**: Only `TELEGRAM_CHAT_ID` can use the bot
- **Local API Auth**: Cloud bot token passed as Bearer token
- **ngrok**: HTTPS tunnel with random subdomain
- **No exposed ports** on local machine (ngrok handles ingress)

## Troubleshooting

### "Local JARVIS offline" but it's running
- Check ngrok is running: `ngrok http 8080`
- Verify `cloud_public_url` in config matches ngrok HTTPS URL
- Check cloud bot logs: `railway logs` or platform equivalent
- Test local API: `curl https://your-ngrok-url/api/jarvis/health`

### Cloud bot not responding
- Check Railway/Render logs
- Verify environment variables set
- Test health: `curl https://your-bot.railway.app/api/instances`

### Actions fail
- Check local JARVIS logs for errors
- Verify `cloud_bot_token` matches on both sides
- Test local action directly: `curl -X POST https://ngrok-url/api/jarvis/action -H "Authorization: Bearer token" -d '{"action":"system_status"}'`

## File Structure

```
cloud_bot/
├── main.py              # Cloud bot (FastAPI + Telegram)
├── requirements.txt     # Python dependencies
├── railway.toml         # Railway config
├── Dockerfile           # Container deployment
├── .env.example         # Environment template
├── setup_ngrok.py       # Ngrok tunnel setup helper
└── README.md            # This file

plugins/
└── cloud_connector.py   # Local JARVIS plugin
```

## Next Steps

1. Deploy cloud bot to Railway
2. Run `python cloud_bot/setup_ngrok.py` locally
3. Start JARVIS → Cloud connector auto-connects
4. Test from Telegram!