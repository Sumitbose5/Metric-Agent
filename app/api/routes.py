from fastapi import APIRouter, HTTPException
from app.agent.worker import active_sessions
import asyncio
import logging

logger = logging.getLogger("aria-worker")
router = APIRouter()

@router.post("/notify-code-result")
async def notify_code_result(data: dict):
    interview_id = data.get("interviewId")
    result = data.get("result", {})
    code = data.get("candidateCode")

    entry = active_sessions.get(interview_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Interview session not found")

    session = entry["session"]  # AgentSession
    agent = entry["agent"]      # Agent

    passed_count = result.get("passedCount", 0)
    total_count = result.get("totalCount", 0)
    verdict = result.get("verdict", "")
    failed_case = result.get("failedCase")

    is_accepted = verdict == "ACCEPTED" or passed_count == total_count

    failed_case_info = ""
    if failed_case:
        failed_case_info = (
            f"\nFailed Test Case:\n"
            f"  Input: {failed_case.get('input')}\n"
            f"  Expected Output: {failed_case.get('expected')}\n"
            f"  Candidate's Output: {failed_case.get('actual')}\n"
        )

    # 1. Inject submission details into chat context
    context_message = (
        f"[SYSTEM UPDATE] The candidate just submitted their code.\n"
        f"Result: {passed_count}/{total_count} test cases passed. Verdict: {verdict}\n"
        f"{failed_case_info}"
        f"Code Submitted:\n```\n{code}\n```"
    )
    chat_ctx = agent.chat_ctx.copy()
    chat_ctx.add_message(role="user", content=context_message)
    await agent.update_chat_ctx(chat_ctx)

    logger.info(f"Code submission processed for interview {interview_id}")

    # 2. Build the speech string
    if is_accepted:
        speech_text = (
            f"Congratulations! You've passed all {total_count} test cases. "
            f"Well done! Now, can you walk me through the time and space complexity of your solution?"
        )
    else:
        hint_context = ""
        if failed_case:
            hint_context = (
                f"For example, when the input was {failed_case.get('input')}, "
                f"your code returned {failed_case.get('actual')} "
                f"but the expected output was {failed_case.get('expected')}. "
            )
        speech_text = (
            f"You passed {passed_count} out of {total_count} test cases. "
            f"{hint_context}"
            f"Take a closer look at your logic and see if you can spot what might be going wrong."
        )

    # 3. ✅ FIXED: Properly schedule say() on the agent's event loop
    try:
        # Get the agent's running event loop
        agent_loop = entry.get("loop") or asyncio.get_event_loop()

        # Use asyncio.run_coroutine_threadsafe if agent runs on a different loop,
        # or directly schedule via create_task on the same loop
        async def _speak():
            try:
                handle = session.say(speech_text, allow_interruptions=True)
                # SpeechHandle: await it using its internal done event
                if hasattr(handle, "wait_for_playout"):
                    await handle.wait_for_playout()  # LiveKit agents v0.x
                elif hasattr(handle, "__await__"):
                    await handle
                else:
                    # Fallback: give TTS time to dispatch
                    await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Error during say(): {e}")

        # Schedule as a background task so HTTP response isn't blocked
        asyncio.ensure_future(_speak())

    except Exception as e:
        logger.error(f"Failed to trigger speech for interview {interview_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Speech dispatch failed: {str(e)}")

    return {"status": "success"}