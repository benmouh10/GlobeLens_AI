"""
GlobeLens AI — ReadingListController

Named, ordered collections of saved events/articles, layered on top of the flat
bookmarks table:

    GET    /users/{user_id}/reading-lists
    POST   /users/{user_id}/reading-lists
    GET    /users/{user_id}/reading-lists/{list_id}
    PUT    /users/{user_id}/reading-lists/{list_id}
    DELETE /users/{user_id}/reading-lists/{list_id}
    POST   /users/{user_id}/reading-lists/{list_id}/items
    DELETE /users/{user_id}/reading-lists/{list_id}/items/{item_id}
    PUT    /users/{user_id}/reading-lists/{list_id}/items/reorder
    GET    /users/{user_id}/reading-lists/{list_id}/export   (print-friendly HTML)
"""
import html
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.auth_controller import get_current_user
from app.controllers.user_controller import _parse_uuid, _require_self_or_admin
from app.core.database import get_db
from app.entities.models import Article, Event, ReadingList, ReadingListItem, User

router = APIRouter()


# ── Request models ─────────────────────────────────────────────────────────────
class CreateListRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    is_public: bool = False


class UpdateListRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    is_public: Optional[bool] = None


class AddItemRequest(BaseModel):
    event_id: Optional[str] = None
    article_id: Optional[str] = None
    note: Optional[str] = None


class ReorderRequest(BaseModel):
    item_ids: List[str]


# ── Helpers ────────────────────────────────────────────────────────────────────
def _serialize_list(rl: ReadingList, item_count: int) -> dict:
    return {
        "id": str(rl.id),
        "name": rl.name,
        "description": rl.description,
        "is_public": bool(rl.is_public),
        "item_count": item_count,
        "created_at": rl.created_at.isoformat() if rl.created_at else None,
        "updated_at": rl.updated_at.isoformat() if rl.updated_at else None,
    }


def _serialize_event_item(item: ReadingListItem, event: Optional[Event]) -> dict:
    return {
        "id": str(item.id),
        "type": "event",
        "position": item.position,
        "note": item.note,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "target": (
            {
                "id": str(event.id),
                "title": event.title,
                "topic": event.topic or "WORLD",
                "country": event.country or "Unknown",
                "summary": event.summary,
                "importance_score": event.importance_score,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            if event
            else None
        ),
    }


def _serialize_article_item(item: ReadingListItem, article: Optional[Article]) -> dict:
    return {
        "id": str(item.id),
        "type": "article",
        "position": item.position,
        "note": item.note,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "target": (
            {
                "id": str(article.id),
                "title": article.title,
                "origin": article.origin.value if hasattr(article.origin, "value") else article.origin,
                "publication_status": (
                    article.publication_status.value
                    if hasattr(article.publication_status, "value")
                    else article.publication_status
                ),
                "created_at": article.created_at.isoformat() if article.created_at else None,
            }
            if article
            else None
        ),
    }


async def _get_list_or_404(
    db: AsyncSession, user_uuid: uuid.UUID, list_id: uuid.UUID
) -> ReadingList:
    rl = await db.get(ReadingList, list_id)
    if not rl or rl.user_id != user_uuid:
        raise HTTPException(status_code=404, detail="Reading list not found")
    return rl


async def _serialize_items(db: AsyncSession, list_id: uuid.UUID) -> List[dict]:
    """Load a list's items and hydrate their event/article target in two batched
    queries rather than one lookup per row."""
    items = (
        await db.execute(
            select(ReadingListItem)
            .where(ReadingListItem.list_id == list_id)
            .order_by(ReadingListItem.position.asc(), ReadingListItem.created_at.asc())
        )
    ).scalars().all()

    if not items:
        return []

    event_ids = [i.event_id for i in items if i.event_id]
    article_ids = [i.article_id for i in items if i.article_id]

    events = {}
    if event_ids:
        rows = (await db.execute(select(Event).where(Event.id.in_(event_ids)))).scalars().all()
        events = {e.id: e for e in rows}
    articles = {}
    if article_ids:
        rows = (await db.execute(select(Article).where(Article.id.in_(article_ids)))).scalars().all()
        articles = {a.id: a for a in rows}

    out: List[dict] = []
    for item in items:
        if item.event_id:
            out.append(_serialize_event_item(item, events.get(item.event_id)))
        elif item.article_id:
            out.append(_serialize_article_item(item, articles.get(item.article_id)))
    return out


# ── Routes ─────────────────────────────────────────────────────────────────────
@router.get("/{user_id}/reading-lists", summary="List a user's reading lists")
async def list_reading_lists(
    user_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_uuid = _parse_uuid(user_id)
    _require_self_or_admin(current_user, user_uuid)

    counts = dict(
        (
            await db.execute(
                select(ReadingListItem.list_id, func.count(ReadingListItem.id))
                .group_by(ReadingListItem.list_id)
            )
        ).all()
    )
    lists = (
        await db.execute(
            select(ReadingList)
            .where(ReadingList.user_id == user_uuid)
            .order_by(ReadingList.updated_at.desc().nullslast(), ReadingList.created_at.desc())
        )
    ).scalars().all()

    return {"reading_lists": [_serialize_list(rl, counts.get(rl.id, 0)) for rl in lists]}


@router.post(
    "/{user_id}/reading-lists",
    status_code=status.HTTP_201_CREATED,
    summary="Create a reading list",
)
async def create_reading_list(
    payload: CreateListRequest,
    user_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_uuid = _parse_uuid(user_id)
    _require_self_or_admin(current_user, user_uuid)

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")

    existing = await db.execute(
        select(ReadingList).where(ReadingList.user_id == user_uuid, ReadingList.name == name)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="A list with that name already exists")

    rl = ReadingList(
        user_id=user_uuid,
        name=name,
        description=payload.description,
        is_public=payload.is_public,
    )
    db.add(rl)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A list with that name already exists")
    await db.refresh(rl)
    # No items yet: creating a list and adding nothing is a valid empty list.
    return _serialize_list(rl, 0)


@router.get("/{user_id}/reading-lists/{list_id}", summary="Get a reading list with its items")
async def get_reading_list(
    user_id: str = Path(...),
    list_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_uuid = _parse_uuid(user_id)
    list_uuid = _parse_uuid(list_id)
    rl = await _get_list_or_404(db, user_uuid, list_uuid)
    # A public list is readable by any authenticated reader who knows its owner.
    if not rl.is_public:
        _require_self_or_admin(current_user, user_uuid)

    items = await _serialize_items(db, list_uuid)
    return {**_serialize_list(rl, len(items)), "items": items}


@router.put("/{user_id}/reading-lists/{list_id}", summary="Rename / update a reading list")
async def update_reading_list(
    payload: UpdateListRequest,
    user_id: str = Path(...),
    list_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_uuid = _parse_uuid(user_id)
    _require_self_or_admin(current_user, user_uuid)
    rl = await _get_list_or_404(db, user_uuid, _parse_uuid(list_id))

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        dup = await db.execute(
            select(ReadingList).where(
                ReadingList.user_id == user_uuid,
                ReadingList.name == name,
                ReadingList.id != rl.id,
            )
        )
        if dup.scalars().first():
            raise HTTPException(status_code=409, detail="A list with that name already exists")
        rl.name = name
    if payload.description is not None:
        rl.description = payload.description
    if payload.is_public is not None:
        rl.is_public = payload.is_public

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A list with that name already exists")
    await db.refresh(rl)
    count = (
        await db.execute(
            select(func.count(ReadingListItem.id)).where(ReadingListItem.list_id == rl.id)
        )
    ).scalar_one()
    return _serialize_list(rl, count)


@router.delete(
    "/{user_id}/reading-lists/{list_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a reading list",
)
async def delete_reading_list(
    user_id: str = Path(...),
    list_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_uuid = _parse_uuid(user_id)
    _require_self_or_admin(current_user, user_uuid)
    rl = await _get_list_or_404(db, user_uuid, _parse_uuid(list_id))
    await db.delete(rl)
    await db.commit()
    return None


@router.post(
    "/{user_id}/reading-lists/{list_id}/items",
    status_code=status.HTTP_201_CREATED,
    summary="Add an event or article to a reading list",
)
async def add_reading_list_item(
    payload: AddItemRequest,
    user_id: str = Path(...),
    list_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_uuid = _parse_uuid(user_id)
    _require_self_or_admin(current_user, user_uuid)
    list_uuid = _parse_uuid(list_id)
    rl = await _get_list_or_404(db, user_uuid, list_uuid)

    has_event = payload.event_id is not None
    has_article = payload.article_id is not None
    if has_event == has_article:
        raise HTTPException(
            status_code=400, detail="Provide exactly one of event_id or article_id"
        )

    event_uuid = _parse_uuid(payload.event_id) if has_event else None
    article_uuid = _parse_uuid(payload.article_id) if has_article else None

    if event_uuid:
        if not await db.get(Event, event_uuid):
            raise HTTPException(status_code=404, detail="Event not found")
        dup = await db.execute(
            select(ReadingListItem).where(
                ReadingListItem.list_id == list_uuid, ReadingListItem.event_id == event_uuid
            )
        )
    else:
        if not await db.get(Article, article_uuid):
            raise HTTPException(status_code=404, detail="Article not found")
        dup = await db.execute(
            select(ReadingListItem).where(
                ReadingListItem.list_id == list_uuid, ReadingListItem.article_id == article_uuid
            )
        )

    existing = dup.scalars().first()
    if existing:
        # Idempotent: refetching and re-adding is a client retry, not an error.
        return {"message": "Already in this list", "item_id": str(existing.id)}

    next_pos = (
        await db.execute(
            select(func.coalesce(func.max(ReadingListItem.position), -1)).where(
                ReadingListItem.list_id == list_uuid
            )
        )
    ).scalar_one() + 1

    item = ReadingListItem(
        list_id=list_uuid,
        event_id=event_uuid,
        article_id=article_uuid,
        position=next_pos,
        note=payload.note,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return {
        "message": "Added to list",
        "item_id": str(item.id),
        "list_id": str(rl.id),
        "position": item.position,
    }


@router.delete(
    "/{user_id}/reading-lists/{list_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an item from a reading list",
)
async def remove_reading_list_item(
    user_id: str = Path(...),
    list_id: str = Path(...),
    item_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_uuid = _parse_uuid(user_id)
    _require_self_or_admin(current_user, user_uuid)
    list_uuid = _parse_uuid(list_id)
    await _get_list_or_404(db, user_uuid, list_uuid)

    item = await db.get(ReadingListItem, _parse_uuid(item_id))
    if not item or item.list_id != list_uuid:
        raise HTTPException(status_code=404, detail="Item not found")
    await db.delete(item)
    await db.commit()
    return None


@router.put(
    "/{user_id}/reading-lists/{list_id}/items/reorder",
    summary="Reorder the items in a reading list",
)
async def reorder_reading_list_items(
    payload: ReorderRequest,
    user_id: str = Path(...),
    list_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_uuid = _parse_uuid(user_id)
    _require_self_or_admin(current_user, user_uuid)
    list_uuid = _parse_uuid(list_id)
    await _get_list_or_404(db, user_uuid, list_uuid)

    item_uuids = [_parse_uuid(i) for i in payload.item_ids]
    rows = (
        await db.execute(
            select(ReadingListItem).where(
                ReadingListItem.list_id == list_uuid,
                ReadingListItem.id.in_(item_uuids),
            )
        )
    ).scalars().all()
    by_id = {r.id: r for r in rows}

    missing = [str(i) for i in item_uuids if i not in by_id]
    if missing:
        raise HTTPException(status_code=404, detail=f"Items not in list: {missing}")

    for index, item_uuid in enumerate(item_uuids):
        by_id[item_uuid].position = index

    await db.commit()
    return {"message": "Reordered", "count": len(item_uuids)}


@router.get(
    "/{user_id}/reading-lists/{list_id}/export",
    response_class=HTMLResponse,
    summary="Export a reading list as print-friendly HTML",
)
async def export_reading_list(
    user_id: str = Path(...),
    list_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_uuid = _parse_uuid(user_id)
    list_uuid = _parse_uuid(list_id)
    rl = await _get_list_or_404(db, user_uuid, list_uuid)
    if not rl.is_public:
        _require_self_or_admin(current_user, user_uuid)

    items = await _serialize_items(db, list_uuid)

    rows = []
    for index, item in enumerate(items, start=1):
        target = item.get("target") or {}
        title = html.escape(target.get("title") or "(removed)")
        if item["type"] == "event":
            meta = f"{html.escape(target.get('topic') or 'WORLD')} &middot; {html.escape(target.get('country') or 'Unknown')}"
            summary = target.get("summary") or ""
        else:
            meta = f"Dispatch &middot; {html.escape(str(target.get('publication_status') or ''))}"
            summary = ""
        note = html.escape(item.get("note") or "")
        rows.append(
            f"""
            <li>
              <div class="idx">{index:02d}</div>
              <div class="body">
                <h2>{title}</h2>
                <div class="meta">{meta}</div>
                {f'<p class="summary">{html.escape(summary)}</p>' if summary else ''}
                {f'<p class="note">{note}</p>' if note else ''}
              </div>
            </li>"""
        )

    body = "".join(rows) or "<li class='empty'>This reading list is empty.</li>"
    description = html.escape(rl.description or "")
    generated = html.escape(rl.updated_at.isoformat() if rl.updated_at else "")

    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(rl.name)} — GlobeLens Reading List</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:2.5rem 2rem; background:#fff; color:#111827;
         font-family: Georgia, 'Times New Roman', serif; line-height:1.5; }}
  header {{ border-bottom:2px solid #111827; padding-bottom:1rem; margin-bottom:1.5rem; }}
  .kicker {{ font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
            letter-spacing:.18em; text-transform:uppercase; color:#6b7280; }}
  h1 {{ font-size:1.9rem; margin:.4rem 0 .5rem; }}
  .desc {{ color:#374151; font-size:.95rem; margin:0 0 .6rem; max-width:60ch; }}
  .gen {{ font:400 11px/1 ui-monospace,monospace; color:#9ca3af; }}
  ul {{ list-style:none; margin:0; padding:0; }}
  li {{ display:flex; gap:1rem; padding:1rem 0; border-bottom:1px solid #e5e7eb; break-inside:avoid; }}
  li.empty {{ color:#9ca3af; font-style:italic; }}
  .idx {{ font:700 13px/1.4 ui-monospace,monospace; color:#9ca3af; min-width:2rem; }}
  .body {{ flex:1; }}
  h2 {{ font-size:1.1rem; margin:0 0 .25rem; }}
  .meta {{ font:600 10px/1.4 ui-monospace,monospace; letter-spacing:.12em;
          text-transform:uppercase; color:#2563eb; }}
  .summary {{ margin:.4rem 0 0; color:#374151; font-size:.9rem; }}
  .note {{ margin:.4rem 0 0; color:#6b7280; font-size:.85rem; font-style:italic; }}
  @media print {{ body {{ padding:0; }} .no-print {{ display:none; }} }}
</style></head>
<body>
  <header>
    <div class="kicker">GlobeLens · Reading List</div>
    <h1>{html.escape(rl.name)}</h1>
    {f'<p class="desc">{description}</p>' if description else ''}
    <div class="gen">Exported {generated} · {len(items)} item(s)</div>
  </header>
  <ul>{body}</ul>
  <script>window.onload = function () {{ window.print(); }};</script>
</body></html>"""
    return HTMLResponse(content=document)
