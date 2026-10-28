import uvicorn
import os

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    # proxy_headers=False: same XFF-trust opt-out as server.py (card 11550,
    # W2b) — the guard's peer fallback must stay the real socket peer.
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True,
                proxy_headers=False)
