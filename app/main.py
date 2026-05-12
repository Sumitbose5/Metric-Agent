import asyncio
import uvicorn
from fastapi import FastAPI
from livekit.agents import AgentServer, JobContext
from app.api.routes import router
import os

from dotenv import load_dotenv

load_dotenv()

# 1. Create the AgentServer instance (no entrypoint_fnc in constructor!)
server = AgentServer()

# 2. Register the entrypoint using the decorator
@server.rtc_session(agent_name="Aria")
async def entrypoint(ctx: JobContext):
    # Import your actual logic here to avoid circular imports
    from app.agent.worker import entrypoint as _real_entrypoint
    await _real_entrypoint(ctx)

# 3. FastAPI app
app = FastAPI()
app.include_router(router)

@app.get("/health")
def health():
    return {"status": "ok"}

async def run_services():
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)), loop="asyncio")
    uvicorn_server = uvicorn.Server(config)

    print("🚀 Metric Backend: FastAPI + LiveKit AgentServer starting...")

    await asyncio.gather(
        uvicorn_server.serve(),
        server.run(),
    )

if __name__ == "__main__":
    try:
        asyncio.run(run_services())
    except KeyboardInterrupt:
        print("\nStopping Metric services...")