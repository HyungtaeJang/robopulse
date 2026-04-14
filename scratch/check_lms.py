import os
import httpx
from openai import OpenAI

# 테스트할 후보 주소들
targets = [
    "http://localhost:1234/v1",
    "http://127.0.0.1:1234/v1",
    "http://10.231.128.123:1234/v1"
]

for url in targets:
    print(f"\n--- Testing: {url} ---")
    try:
        # 1. httpx로 직접 시도
        with httpx.Client(proxies={}, trust_env=False, timeout=2.0) as client:
            resp = client.get(f"{url}/models")
            print(f"Direct HTTP Status: {resp.status_code}")
            
        # 2. OpenAI 클라이언트로 시도
        oa = OpenAI(base_url=url, api_key="lm-studio", http_client=httpx.Client(proxies={}, trust_env=False))
        models = oa.models.list()
        print(f"Success! Models found: {len(models.data)}")
        for m in models.data:
            print(f"  - {m.id}")
            
    except Exception as e:
        print(f"Failed: {type(e).__name__} - {e}")
