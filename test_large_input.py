import asyncio
import json
import httpx
import os

async def main():
    base_url = "https://api.minimaxi.com/v1/chat/completions"
    
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("VLLM_API_KEY")
    if not api_key or api_key == "dummy_key":
        print("No valid API key found.")
        return
        
    # Create a large prompt around 7000 tokens (approx 28000 characters)
    large_text = "hello world " * 4000
    payload = {
        "model": "MiniMax-M2",
        "messages": [{"role": "user", "content": large_text}],
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            base_url,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30
        )
        print(resp.status_code)
        print(resp.text[:500])

asyncio.run(main())
