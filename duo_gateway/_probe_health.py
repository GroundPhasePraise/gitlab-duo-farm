import urllib.request, socket

s = socket.socket(); s.settimeout(3)
print("8088 listening:", "YES" if s.connect_ex(("127.0.0.1", 8088)) == 0 else "NO")
s.close()
try:
    r = urllib.request.urlopen("http://127.0.0.1:8088/health", timeout=6)
    print("health:", r.status, r.read()[:150])
except Exception as e:
    print("health ERR:", e)