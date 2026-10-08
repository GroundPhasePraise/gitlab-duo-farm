"""vision_bridge.py — computer-vision sidecar for the Duo gateway.

Duo Chat UI is text-only, so images are described by a local vision model
(qwen3-vl-plus via the dashscope OpenAI-compatible proxy on :16432) and the
description is injected into the Duo prompt as [Attached image].

Also provides screen capture -> description (the `screenshot` server tool),
giving the Duo model eyes on this PC.
"""
import base64
import io
import json
import os
import urllib.request

VISION_URL = os.environ.get("GATEWAY_VISION_URL", "http://127.0.0.1:16432/v1/chat/completions")
VISION_MODEL = os.environ.get("GATEWAY_VISION_MODEL", "qwen3-vl-plus")
VISION_TIMEOUT = int(os.environ.get("GATEWAY_VISION_TIMEOUT", "120"))
MAX_DESC = 6000


def _as_data_uri(src: str) -> str:
    """Accept http(s) URL, data: URI, or local file path -> data URI."""
    src = src.strip()
    if src.startswith("data:"):
        return src
    if src.startswith("http://") or src.startswith("https://"):
        with urllib.request.urlopen(src, timeout=60) as r:
            b = r.read()
        ext = "png" if b[:8] == b"\x89PNG\r\n\x1a\n" else "jpeg"
        return f"data:image/{ext};base64," + base64.b64encode(b).decode()
    p = os.path.expanduser(src)
    if os.path.exists(p):
        b = open(p, "rb").read()
        ext = p.rsplit(".", 1)[-1].lower()
        if ext in ("jpg", "jpeg"):
            mime = "jpeg"
        elif ext == "webp":
            mime = "webp"
        else:
            mime = "png"
        return f"data:image/{mime};base64," + base64.b64encode(b).decode()
    raise ValueError(f"image source not found: {src[:120]}")


def describe_image(image_src: str, question: str = "") -> str:
    """Describe one image via the local vision model. Returns text."""
    data_uri = _as_data_uri(image_src)
    q = question or ("Describe this image in detail for a text-only assistant that cannot see it. "
                     "Include all readable text, UI elements, layouts, numbers, and anything that looks "
                     "like an error, status, or credential (mask nothing). Be exhaustive but factual.")
    payload = {
        "model": VISION_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_uri}},
            {"type": "text", "text": q},
        ]}],
        "max_tokens": 2000,
    }
    req = urllib.request.Request(VISION_URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=VISION_TIMEOUT) as r:
        d = json.load(r)
    txt = (d["choices"][0]["message"].get("content") or "").strip()
    return txt[:MAX_DESC] if txt else "[vision: empty description]"


def grab_screen(max_dim: int = 1568) -> bytes:
    """Capture the primary screen as PNG bytes (PIL ImageGrab)."""
    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=False)
    if max(img.size) > max_dim:
        img = img.resize((int(img.width * max_dim / max(img.size)),
                          int(img.height * max_dim / max(img.size))))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def screenshot_describe(question: str = "", save_path: str = "") -> str:
    """Capture screen -> vision description (the `screenshot` server tool)."""
    png = grab_screen()
    if save_path:
        try:
            open(save_path, "wb").write(png)
        except Exception:
            pass
    data_uri = "data:image/png;base64," + base64.b64encode(png).decode()
    return describe_image(data_uri, question)
