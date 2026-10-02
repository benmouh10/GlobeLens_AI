from fastapi import APIRouter, HTTPException
from typing import List
from pydantic import BaseModel, EmailStr

router = APIRouter()

class SubscribeRequest(BaseModel):
    email: EmailStr
    interests: List[str] = []
    frequency: str = "daily" # daily or weekly

@router.post("/subscribe", summary="Subscribe to GlobeLens AI Newsletter")
async def subscribe_newsletter(req: SubscribeRequest):
    """
    Not implemented.

    There is no subscribers table, no mail transport and no scheduler, so this
    previously answered "Successfully subscribed" without recording or sending
    anything. A caller cannot distinguish that from a real subscription, which
    is how unsubmitted newsletters quietly accumulate.
    """
    raise HTTPException(
        status_code=501,
        detail="Newsletter delivery is not implemented: no subscriber storage "
               "or mail transport is configured.",
    )

@router.post("/send-digest", summary="Admin: Trigger email digest generation")
async def send_digest():
    """
    Not implemented, and deliberately unauthenticated.

    This is the endpoint that would send real mail to every subscriber, so it
    must not become callable without auth when it is implemented.
    """
    raise HTTPException(
        status_code=501,
        detail="Digest dispatch is not implemented: no mail transport or "
               "queue is configured.",
    )
