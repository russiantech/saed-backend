import requests
import json
import time

for i in range(5):
    data = {"email": "test@test.com", "amount": 2500000, "reference": f"TEST-REQ-{i}-{int(time.time())}", "currency": "NGN"}
    try:
        r = requests.post(
            "https://api.paystack.co/transaction/initialize",
            json=data,
            headers={"Authorization": "Bearer sk_test_aebe538479eb20d4b4a87c128d212edc4184e379"},
            timeout=15,
        )
        print(f"Attempt {i+1}: Status={r.status_code}, Body={r.text[:200]}")
    except Exception as e:
        print(f"Attempt {i+1}: {type(e).__name__}: {e}")
    time.sleep(0.5)
