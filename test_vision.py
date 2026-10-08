"""test_vision.py — check the local dashscope rotator for vision models + do a tiny vision call."""
import base64
import io
import json

import httpx

BASE = "http://127.0.0.1:16432/v1"

try:
    r = httpx.get(BASE + "/models", timeout=15)
    models = [m["id"] for m in r.json().get("data", [])]
    vl = [m for m in models if "vl" in m.lower() or "vision" in m.lower()]
    print("models:", len(models), "| vision:", vl[:10])
except Exception as e:
    print("models err:", str(e)[:80])
    raise SystemExit(1)

# tiny vision test: 1x1 red png
png = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
if vl:
    model = vl[0]
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
            {"type": "text", "text": "What color is this pixel? One word."},
        ]}],
        "max_tokens": 10,
    }
    try:
        r = httpx.post(BASE + "/chat/completions", json=body, timeout=60,
                       headers={"Authorization": "Bearer rotator"})
        j = r.json()
        print("vision call:", r.status_code, json.dumps(j.get("choices", [{}])[0].get("message", {}))[:200] or j)
    except Exception as e:
        print("vision err:", str(e)[:100])
