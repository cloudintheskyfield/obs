import asyncio
import json
import httpx
import os

async def main():
    base_url = "https://api.minimaxi.com/v1/chat/completions"
    api_key = os.getenv("MINIMAX_API_KEY", "dummy_key") # We can just test if the payload is accepted
    
    # Try calling without max_tokens
    payload = {
        "model": "MiniMax-M2",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    
    # Let's get the actual api key from .env
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("VLLM_API_KEY")
    if not api_key or api_key == "dummy_key":
        print("No valid API key found.")
        return
        
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            base_url,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"}
        )
        print(resp.status_code)
        print(resp.text[:500])

asyncio.run(main())
