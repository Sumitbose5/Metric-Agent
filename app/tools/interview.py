import json
import os
import httpx
from datetime import datetime
from livekit import agents
from app.utils.get_chat import finalize_and_export_transcript

from dotenv import load_dotenv

load_dotenv()

class InterviewTools:
    def __init__(self, room, interview_id, user_id):
        # We store these as instance variables
        self.room = room
        self.interview_id = interview_id
        self.user_id = user_id
        # We will set this in worker.py after the agent is created
        self.agent = None 
        self.session = None
        self.core_backend_url = os.getenv("API_BASE_URL", "http://localhost:3000/api")
        # ✅ NEW: Manual message buffer (since chat_ctx is not accessible)
        self.conversation_buffer = []

    @agents.function_tool(description="Returns the current date and time.")
    async def get_current_date_and_time(self) -> str:
        current_datetime = datetime.now().strftime("%B %d, %Y at %I:%M %p")
        return f"The current date and time is {current_datetime}"

    @agents.function_tool(description="Retrieves a technical DSA problem for the candidate.")
    async def get_dsa_problem(self) -> str:
        try:
            async with httpx.AsyncClient() as client:
                print("Inside get_dsa_problem............")
                response = await client.get(
                    f"{self.core_backend_url}/interview/question",
                    params={"userId": self.user_id, "interviewId": self.interview_id}
                )
                response.raise_for_status()
                problem_data = response.json()

            # Now we use the self.room we passed in the constructor
            await self.room.local_participant.publish_data(
                json.dumps({"type": "NEW_DSA_PROBLEM", "data": problem_data}).encode('utf-8'),
                topic="dsa_updates"
            )

            problem_info = problem_data.get('problem', {})
            return (f"The problem is: {problem_info.get('title')}. "
                    f"Description: {problem_info.get('description')}. "
                    "Please read this naturally to the candidate.")
        except Exception as e:
            return f"Error fetching problem: {str(e)}"


    @agents.function_tool(description="Ends the interview session.")
    async def end_interview(self) -> str:
        print(f"--- [FLOW] Ending session for {self.interview_id} ---")

        payload = json.dumps({"type": "STATE_CHANGE", "state": "GENERATING_FEEDBACK"})
        await self.room.local_participant.publish_data(payload.encode('utf-8'), topic="interview_events")

        # ✅ PROPER: Pass session (not buffer) so we can access session.history
        # Session has the official conversation history from LiveKit SDK
        if self.session:
            await finalize_and_export_transcript(self.session, self.interview_id)
        else:
            print("⚠️ Warning: Session not available for transcript export")

        await self.room.disconnect()
        return "Interview concluded."
