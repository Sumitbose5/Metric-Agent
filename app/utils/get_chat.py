import os
import httpx
import logging
import json

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("aria-worker")

async def finalize_and_export_transcript(session, interview_id: str):
    print(f"--- [DEBUG] Finalizing transcript for interview {interview_id} ---")
    
    try:
        transcript = []
        
        # Access session.history (a ChatContext object)
        if hasattr(session, 'history') and session.history:
            items_list = getattr(session.history, 'items', [])
            logger.info(f"Accessing session.history with {len(items_list)} items")
            
            for item in items_list:
                try:
                    # OFFICIAL APPROACH: Use item.type to filter
                    item_type = getattr(item, 'type', None)
                    
                    if item_type == "message":
                        # ✅ THE FIX: Use 'item' directly. It IS the ChatMessage.
                        role = getattr(item, 'role', '')
                        
                        # Convert Enum (system/user/assistant) to string if necessary
                        if hasattr(role, 'value'):
                            role = role.value
                        
                        # Use the text_content property as per official 1.x docs
                        text = getattr(item, 'text_content', '')
                        
                        if role and text:
                            transcript.append({
                                "role": str(role),
                                "text": text
                            })
                            logger.debug(f"✅ Captured {role} message")
                    
                    # Skip non-message items (tool calls, etc.)
                    elif item_type in ("function_call", "function_call_output", "agent_handoff"):
                        continue
                
                except Exception as e:
                    logger.warning(f"Error processing item: {e}")
                    continue
        else:
            logger.warning("session.history not available")

        # ... rest of your httpx logic ...
        
        # If history is empty, fall back to buffer (in case it was manually populated)
        if not transcript:
            logger.info("No messages from session.history, checking buffer fallback")
            # Note: conversation_buffer would have been populated by events
            # but we prefer session.history as it's the official source
        
        print(f"Transcript generated with {len(transcript)} messages.")
        logger.info(f"Transcript size: {len(transcript)} messages")
        
        # ✅ Don't send empty transcripts — backend expects valid conversation
        if not transcript:
            logger.warning(f"⚠️ Warning: Empty transcript for interview {interview_id}")
            return False

        async with httpx.AsyncClient(timeout=30.0) as client:
            base_url = os.getenv("API_BASE_URL", "http://localhost:3000/api")
            url = f"{base_url}/interview/end"
            payload = {
                "interviewId": interview_id,
                "conversation": transcript
            }
            
            # Debug: show first 500 chars of payload
            payload_str = json.dumps(payload, indent=2)
            logger.debug(f"Sending payload ({len(payload_str)} chars): {payload_str[:500]}...")
            print(f"Sending payload with {len(transcript)} messages")
            
            response = await client.post(url, json=payload)
            response.raise_for_status()
            print(f"✅ Successfully exported transcript for {interview_id}")
            logger.info(f"✅ Transcript exported successfully: {len(transcript)} messages")
            return True

    except Exception as e:
        logger.error(f"❌ CRITICAL ERROR: Could not export transcript to backend: {e}", exc_info=True)
        print(f"❌ CRITICAL ERROR: Could not export transcript to backend: {e}")
        return False