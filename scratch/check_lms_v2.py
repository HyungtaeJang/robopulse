import os
import httpx
import json
from openai import OpenAI

url = "http://127.0.0.1:1234/v1"
print(f"--- Diagnosing LM Studio at {url} ---")

# 1. 최하단 레벨의 HTTP 요청 테스트 (가장 확실함)
print("\n[Step 1] Direct HTTP Get Test (no library):")
try:
    with httpx.Client(proxy=None, trust_env=False, timeout=5.0) as client:
        resp = client.get(f"{url}/models")
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            print("Successfully reached LM Studio via HTTP!")
        else:
            print(f"Response Body: {resp.text}")
except Exception as e:
    print(f"HTTP Test Failed: {type(e).__name__} - {e}")

# 2. OpenAI 클라이언트 테스트 (현재 앱이 사용하는 방식)
print("\n[Step 2] OpenAI Library Test:")
try:
    client = OpenAI(
        base_url=url, 
        api_key="lm-studio", 
        http_client=httpx.Client(proxy=None, trust_env=False)
    )
    models = client.models.list()
    print(f"Library Success! Found {len(models.data)} models.")
except Exception as e:
    print(f"Library Test Failed: {type(e).__name__} - {e}")
    
print("\n--- Additional Check: LM Studio Settings ---")
print("1. LM Studio 하단 'Server' 탭에서 'Server Is ON' 인지 확인해주세요.")
print("2. 'CORS' 옵션이 켜져 있는지 확인해주세요.")
print("3. 'Port'가 1234가 맞는지 확인해주세요.")
