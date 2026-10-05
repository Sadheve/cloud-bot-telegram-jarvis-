#!/usr/bin/env python3
"""
Ngrok Tunnel Setup for JARVIS Cloud Connector

This script helps you set up an ngrok tunnel so the cloud bot can reach your local JARVIS.
Run this after starting JARVIS locally.
"""

import os
import sys
import json
import subprocess
import time
import requests
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "api_keys.json"

def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

def check_ngrok():
    """Check if ngrok is installed."""
    try:
        result = subprocess.run(["ngrok", "version"], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False

def start_ngrok(port=8080):
    """Start ngrok tunnel."""
    try:
        # Start ngrok in background
        process = subprocess.Popen(
            ["ngrok", "http", str(port), "--log=stdout"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Wait for ngrok to start and get the public URL
        time.sleep(3)
        
        # Get tunnel info from ngrok API
        try:
            response = requests.get("http://localhost:4040/api/tunnels", timeout=5)
            tunnels = response.json().get("tunnels", [])
            for tunnel in tunnels:
                if tunnel["proto"] == "https":
                    return tunnel["public_url"], process
        except Exception:
            pass
        
        return None, process
    except Exception as e:
        print(f"Error starting ngrok: {e}")
        return None, None

def main():
    print("🔧 JARVIS Ngrok Tunnel Setup")
    print("=" * 40)
    
    # Check ngrok
    if not check_ngrok():
        print("❌ ngrok not found!")
        print("Install from: https://ngrok.com/download")
        print("Or: winget install ngrok (Windows)")
        return 1
    
    print("✅ ngrok found")
    
    # Load config
    config = load_config()
    cloud_bot_url = config.get("cloud_bot_url", "").strip()
    
    if not cloud_bot_url:
        print("\n⚠️  Cloud bot URL not configured!")
        print("Set 'cloud_bot_url' in config/api_keys.json")
        print("Example: https://your-bot.railway.app")
        cloud_bot_url = input("Enter cloud bot URL (or press Enter to skip): ").strip()
        if cloud_bot_url:
            config["cloud_bot_url"] = cloud_bot_url
            save_config(config)
    
    # Start ngrok
    print(f"\n🚀 Starting ngrok tunnel on port 8080...")
    public_url, process = start_ngrok(8080)
    
    if not public_url:
        print("❌ Failed to get ngrok URL")
        print("Check if port 8080 is free and ngrok is authenticated")
        return 1
    
    print(f"✅ Tunnel created: {public_url}")
    
    # Save public URL to config
    config["cloud_public_url"] = public_url
    save_config(config)
    print(f"💾 Saved to config/api_keys.json")
    
    # Test connection to cloud bot
    if cloud_bot_url:
        print(f"\n🔗 Testing connection to cloud bot...")
        try:
            response = requests.get(f"{cloud_bot_url}/api/instances", timeout=10)
            if response.status_code == 200:
                print("✅ Cloud bot reachable!")
                instances = response.json().get("instances", [])
                print(f"   Registered instances: {len(instances)}")
            else:
                print(f"⚠️  Cloud bot responded with status {response.status_code}")
        except Exception as e:
            print(f"⚠️  Could not reach cloud bot: {e}")
    
    print("\n" + "=" * 40)
    print("🎉 Setup complete!")
    print(f"Public URL: {public_url}")
    print("\nNext steps:")
    print("1. Start JARVIS locally")
    print("2. In JARVIS, run: cloud_connector action=start")
    print("3. Or it will auto-start if configured")
    print("\nPress Ctrl+C to stop tunnel and exit")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Stopping tunnel...")
        if process:
            process.terminate()
        print("Done.")

if __name__ == "__main__":
    sys.exit(main())