import os
import json
import logging
import asyncio
from dotenv import load_dotenv

load_dotenv()

from livekit import agents
from livekit.agents import (
    JobContext,
    WorkerOptions,
    cli,
    AgentSession,
    Agent,
    ChatContext,
    function_tool,
    RoomInputOptions,
)
from livekit.plugins import openai, deepgram, silero
from livekit.rtc import TranscriptionSegment
from app.tools.interview import InterviewTools

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aria-worker")

# Global registry to track active sessions (interview_id -> AgentSession)
active_sessions = {}

SYSTEM_PROMPT = """
ROLE:
You are Aria, a professional Senior DSA Interviewer. Your goal is to evaluate the candidate's problem-solving skills across exactly TWO distinct problems.

STRICT INTERVIEW FLOW (DO NOT SKIP STEPS):

STEP 1 — INTRODUCTION:
Greet the candidate warmly and ask for a brief background (name, experience level, preferred language).

STEP 2 — FIRST PROBLEM (Load):
Call 'get_dsa_problem' exactly ONCE to load Problem 1.
Read the problem out loud naturally. Ask if the candidate has any clarifying questions before they begin.

STEP 3 — FIRST PROBLEM (Coding Phase):
Let the candidate write their code. Do NOT call 'get_dsa_problem' again.
Only provide hints if the candidate is clearly stuck. Never reveal the full solution.

STEP 4 — FIRST PROBLEM (Submission & Review):
Wait for a [SYSTEM UPDATE] containing the candidate's submission result.
Once received:
  a. Acknowledge the result (passed/failed) briefly and naturally.
  b. Ask the candidate to explain the TIME complexity of their solution. Wait for their answer.
  c. Ask the candidate to explain the SPACE complexity of their solution. Wait for their answer.
  d. Ask 1-2 follow-up questions based on their approach (e.g. edge cases, trade-offs, alternative approaches).
  e. Wait for the candidate to fully answer all follow-up questions before proceeding.
DO NOT move to Step 5 until ALL of Step 4 is complete.

STEP 5 — SECOND PROBLEM (Load):
ONLY after Step 4 is fully concluded, call 'get_dsa_problem' exactly ONCE to load Problem 2.
Read the problem out loud naturally. Ask if the candidate has any clarifying questions before they begin.

STEP 6 — SECOND PROBLEM (Coding Phase):
Let the candidate write their code. Do NOT call 'get_dsa_problem' again.
Only provide hints if the candidate is clearly stuck. Never reveal the full solution.

STEP 7 — SECOND PROBLEM (Submission & Review):
Wait for a [SYSTEM UPDATE] containing the candidate's submission result.
Once received:
  a. Acknowledge the result (passed/failed) briefly and naturally.
  b. Ask the candidate to explain the TIME complexity of their solution. Wait for their answer.
  c. Ask the candidate to explain the SPACE complexity of their solution. Wait for their answer.
  d. Ask 1-2 follow-up questions based on their approach (e.g. edge cases, trade-offs, alternative approaches).
  e. Wait for the candidate to fully answer all follow-up questions before proceeding.
DO NOT move to Step 8 until ALL of Step 7 is complete.

STEP 8 — CLOSING:
Once Step 7 is fully complete, wrap up the interview naturally like a real interviewer would.
Thank the candidate sincerely for their time and effort. Mention that it was a pleasure speaking with them.
Tell them the team will be in touch regarding next steps.
ONLY AFTER delivering the closing remarks, call 'end_interview'.

CRITICAL RULES FOR TOOLS:
- 'get_dsa_problem' must be called EXACTLY TWICE in the entire interview: once at Step 2, once at Step 5.
- NEVER call 'get_dsa_problem' while the candidate is actively coding.
- NEVER call 'end_interview' without first completing the closing remarks in Step 8.
- NEVER skip the complexity discussion and follow-up questions after either submission.
- ALWAYS wait for the candidate's response before moving to the next question or step.
- SILENT EXECUTION: ALL tool and function calls must be executed silently and invisibly.
  Never say, announce, or hint that you are calling a function or tool.
  Never speak phrases like "calling get_dsa_problem", "invoking end_interview",
  "function=...", "let me fetch...", or any variation of it.
  The candidate must never be aware that any tool is being used.
  Simply present the result naturally as part of the conversation.

VOICE PRESENTATION RULES:
- NATURAL SPEECH: Read the problem description naturally. Do not read out brackets, symbols, or formatting characters.
- NO MARKDOWN: Use plain conversational text only.
- CONCISENESS: Keep non-problem responses to 1-3 sentences unless discussing complexity or follow-ups.
- NO ANSWERS: Provide hints only. Never give away the full solution.
- NO SCORES: Do not rate or score the candidate. Simply thank them at the end.
- ONE QUESTION AT A TIME: Ask time complexity, then space complexity, then follow-ups — one at a time. Do not stack multiple questions in a single turn.
"""


class AriaAgent(Agent):
    """Aria - Senior DSA Interviewer Agent"""

    def __init__(self, interview_tools: InterviewTools) -> None:
        super().__init__(
            instructions=SYSTEM_PROMPT,
            # Tools are passed as a list of bound methods from your tool class
            tools=[
                interview_tools.get_dsa_problem,
                interview_tools.end_interview,
            ],
        )
        self._interview_tools = interview_tools

    async def on_enter(self) -> None:
        """Called when the agent starts — send the opening greeting."""
        await self.session.generate_reply(
            instructions="Greet the candidate warmly and ask them to introduce themselves and share their background."
        )


async def entrypoint(ctx: JobContext):
    logger.info(f"Connecting to room {ctx.room.name}")

    await ctx.connect()

    # Metadata extraction
    try:
        metadata = json.loads(ctx.job.metadata)
        interview_id = metadata.get("interviewId", "unknown")
        user_id = metadata.get("userId", "unknown")
    except Exception:
        interview_id, user_id = "unknown", "unknown"

    logger.info(f"Starting interview {interview_id} for user {user_id}")

    interview_tools = InterviewTools(ctx.room, interview_id, user_id)
    agent = AriaAgent(interview_tools=interview_tools)

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(),
        llm=openai.LLM(
            model="llama-3.3-70b-versatile",
            base_url="https://api.groq.com/openai/v1",
            api_key=os.getenv("GROQ_API_KEY"),
        ),
        tts=deepgram.TTS(),
    )

    # ✅ FIXED: Set BOTH agent and session for proper transcript access
    interview_tools.agent = agent
    interview_tools.session = session
    
    # ✅ Store BOTH session and agent in the registry (+ tools for API access)
    active_sessions[interview_id] = {
        "session": session,
        "agent": agent,
        "tools": interview_tools,  # ✅ NEW: Store tools for API routes to access buffer
    }

    # ✅ PROPER: Listen to conversation_item_added event for real-time capture
    # This is the official LiveKit SDK approach for capturing conversation history
    def on_conversation_item_added(item) -> None:
        """
        Capture conversation items as they're added to the session.
        This fires for both user and agent messages.
        
        item properties:
        - type: "message" | "function_call" | "function_call_response"
        - role: "user" | "assistant"
        - content: str (for messages) | list[dict] (for multipart content)
        """
        try:
            item_type = getattr(item, 'type', 'unknown')
            logger.debug(f"[CONVERSATION_ITEM] type={item_type}, item={item}")
            
            # Only capture message items, skip function calls
            if item_type != "message":
                logger.debug(f"Skipping non-message item: {item_type}")
                return
            
            role = getattr(item, 'role', None)
            content = getattr(item, 'content', '')
            
            if not content or not role:
                logger.debug(f"Skipping empty item: role={role}, content_len={len(str(content))}")
                return
            
            # Extract text from content (can be string or list)
            text_content = ""
            if isinstance(content, str):
                text_content = content
            elif isinstance(content, list):
                # Content might be list of dicts with 'type' and 'text'
                text_content = " ".join(
                    item.get('text', '') if isinstance(item, dict) else str(item)
                    for item in content
                    if item
                )
            else:
                text_content = str(content)
            
            if text_content.strip():
                interview_tools.conversation_buffer.append({
                    "role": "assistant" if role == "assistant" else "user",
                    "content": text_content
                })
                logger.info(f"✅ Captured {role} message: {text_content[:80]}...")
        except Exception as e:
            logger.error(f"Error in on_conversation_item_added: {e}", exc_info=True)
    
    # Register the event handler
    session.on("conversation_item_added", on_conversation_item_added)
    logger.info("Registered conversation_item_added event handler")

    # Event to wait on until the session closes
    closed_event = asyncio.Event()
    session.on("close", lambda _: closed_event.set())

    try:
        await session.start(room=ctx.room, agent=agent)
        await closed_event.wait()  # ✅ Blocks until session closes naturally
    finally:
        active_sessions.pop(interview_id, None)
        logger.info(f"Session {interview_id} ended.")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name="Aria"))