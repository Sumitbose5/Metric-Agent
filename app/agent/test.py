from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentSession, RunContext
from livekit.agents.llm import function_tool
from livekit.plugins import openai, deepgram, silero

import os
import random
from datetime import datetime

import httpx
import json
 
load_dotenv("../../.env")


class Assistant(Agent):

    def __init__(self):

        # Dummy DSA problem bank
        self.problem_bank = [
            {
                "problem_id": 1,
                "title": "Two Sum",
                "description": "Find two numbers in an array that add up to a target.",
                "difficulty": "Easy"
            },
            {
                "problem_id": 2,
                "title": "Valid Parentheses",
                "description": "Check if a string of brackets is valid.",
                "difficulty": "Easy"
            },
            {
                "problem_id": 3,
                "title": "Reverse Linked List",
                "description": "Reverse a singly linked list.",
                "difficulty": "Easy"
            },
            {
                "problem_id": 4,
                "title": "Longest Substring Without Repeating Characters",
                "description": "Find length of longest substring with unique characters.",
                "difficulty": "Medium"
            },
            {
                "problem_id": 5,
                "title": "Merge Intervals",
                "description": "Merge overlapping intervals.",
                "difficulty": "Medium"
            },
            {
                "problem_id": 6,
                "title": "Course Schedule",
                "description": "Detect if all courses can be completed using graph cycle detection.",
                "difficulty": "Medium"
            },
            {
                "problem_id": 7,
                "title": "Word Ladder",
                "description": "Transform one word to another using shortest path.",
                "difficulty": "Hard"
            },
            {
                "problem_id": 8,
                "title": "Median of Two Sorted Arrays",
                "description": "Find median in logarithmic time.",
                "difficulty": "Hard"
            }
        ]

        super().__init__(
            instructions="""
You are Aria, a professional DSA interviewer.

ROLE:
- Conduct a realistic coding interview.
- Be concise, natural, and conversational in voice.
- Ask one question at a time.
- Use tools when the user requests questions or asks about problems.

RULES:
- Never reveal full solutions.
- Give hints only if candidate is stuck.
- Stay in interviewer role at all times.

TOOL USAGE:
- If candidate asks for a coding problem, call get_a_question.
- If candidate asks for easy, medium or hard problems, call get_problem_by_difficulty.
- If candidate asks what difficulty options exist, call list_available_difficulties.
- If candidate asks you to repeat their name, call repeat_candidate_name.

VOICE OUTPUT RULES:
- All responses must be optimized for spoken voice.
- Never output markdown.
- Never use asterisks, bullets, or formatting symbols.
- Never use bold, italics, or code formatting.
- Speak naturally as if talking aloud.
- Return plain conversational text only.
"""
        )


    @function_tool
    async def get_current_date_and_time(
        self,
        context: RunContext
    ) -> str:
        """
        Use this when the user asks for the current date or time.
        """
        current_datetime = datetime.now().strftime("%B %d, %Y at %I:%M %p")
        return f"The current date and time is {current_datetime}"
    

    @function_tool
    async def get_all_problem_titles(
        self,
        context: RunContext
    ) -> str:
        """
        Use this when the user asks for all problem titles.
        """
        titles = [p["title"] for p in self.problem_bank]
        return "Available problem titles are: " + ", ".join(titles)


    @function_tool
    async def get_a_question(
        self,
        context: RunContext
    ) -> str:
        """
        Use this when the candidate asks for a coding question,
        interview problem, or says give me a DSA problem.
        """
        problem = random.choice(self.problem_bank)

        return (
            f"Problem {problem['problem_id']}: {problem['title']}. "
            f"Difficulty: {problem['difficulty']}. "
            f"{problem['description']}"
        )


    @function_tool
    async def get_problem_by_difficulty(
        self,
        context: RunContext,
        difficulty: str
    ) -> str:
        """
        Use this when the candidate asks for an easy, medium,
        or hard problem.
        """

        filtered = [
            p for p in self.problem_bank
            if p["difficulty"].lower() == difficulty.lower()
        ]

        if not filtered:
            return "No problems found for that difficulty."

        problem = random.choice(filtered)

        return (
            f"{difficulty.title()} problem selected: "
            f"{problem['title']}. "
            f"{problem['description']}"
        )


    @function_tool
    async def list_available_difficulties(
        self,
        context: RunContext
    ) -> str:
        """
        Use this when the candidate asks what problem difficulty
        levels are available.
        """
        return "Available difficulty levels are Easy, Medium, and Hard."


    

    # ... inside your Agent Class ...

    async def get_dsa_problem(
        self,
        ctx: RunContext
    ) -> str:
        """
        Use this when the candidate asks for a DSA problem.
        """
        # 1. Extract IDs from metadata
        metadata = json.loads(ctx.room.local_participant.metadata)
        interview_id = metadata["interviewId"]
        user_id = metadata["userId"]

        # 2. Define API endpoint and query parameters
        base_url = os.getenv("API_BASE_URL", "http://localhost:3000/api")
        url = f"{base_url}/interview/question"
        params = {
            "userId": user_id,
            "interviewId": interview_id
        }
        
        try:
            # httpx handles the '?userId=...&interviewId=...' construction automatically
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                problem_data = response.json()
        except Exception as e:
            return f"Failed to fetch the problem: {str(e)}"

        # 3. Update Agent Memory
        self.chat_context.append(
            {"role": "system", "content": f"Current DSA Problem: {json.dumps(problem_data)}"}
        )

        # 4. Emit event to frontend
        payload = json.dumps({
            "type": "NEW_DSA_PROBLEM",
            "data": problem_data
        })
        
        await ctx.room.local_participant.publish_data(
            payload.encode('utf-8'), 
            topic="dsa_updates"
        )

        return f"I have assigned the problem: {problem_data.get('title', 'DSA Challenge')}. I have shared the details with your interface."
        


    @function_tool
    async def request_next_question(
        self,
        context: RunContext
    ) -> str:
        """
        Placeholder for backend-driven next interview question.
        """
        return "NEXT_QUESTION_PLACEHOLDER"


    @function_tool
    async def code_submitted(
        self,
        context: RunContext,
        candidate_code: str
    ) -> str:
        """
        Placeholder for backend code evaluation.
        """
        return "CODE_SUBMITTED_PLACEHOLDER"


    @function_tool
    async def end_interview(
        self,
        context: RunContext,
        candidate_code: str
    ) -> str:
        """
        Placeholder for ending interview.
        """
        return "END_INTERVIEW_PLACEHOLDER"



async def entrypoint(ctx: agents.JobContext):

    session = AgentSession(
        stt=deepgram.STT(model="nova-2"),

        llm=openai.LLM(
            model="openai/gpt-oss-20b",
            base_url="https://api.groq.com/openai/v1",
            api_key=os.getenv("GROQ_API_KEY"),
        ),

        tts=deepgram.TTS(
            model="aura-2-thalia-en"
        ),

        vad=silero.VAD.load(),
    )

    await session.start(
        room=ctx.room,
        agent=Assistant()
    )

    await session.generate_reply(
        instructions="""
Introduce yourself as Aria.
Ask candidate:
1. Their name
2. Their background
Then wait.
"""
    )


if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint
        )
    )