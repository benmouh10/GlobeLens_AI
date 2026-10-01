"""
GlobeLens AI — AdminController (ADMIN role required for all endpoints)
GET  /admin/dashboard | /admin/users | /admin/stats
PUT  /admin/users/{id}/role | /admin/users/{id}/block | /admin/articles/{id}/hide
DELETE /admin/users/{id} | /admin/comments/{id}
POST /admin/events/promote | /admin/sources
"""
from fastapi import APIRouter, Path, status, Depends, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.controllers.auth_controller import get_current_user
from app.entities.models import User, UserRole
from app.services.embedding_service import EmbeddingService
from app.services.clustering_service import ClusteringService
from app.core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


class UpdateRoleRequest(BaseModel):
    role: str  # GUEST | AUTH_USER | JOURNALIST | ADMIN


class CreateSourceRequest(BaseModel):
    name: str
    url: str
    country: Optional[str] = None
    credibility_score: Optional[float] = 0.5


class PromoteEventRequest(BaseModel):
    event_id: str


@router.get("/dashboard", summary="Admin dashboard overview (ADMIN)")
async def get_dashboard():
    # TODO: IAdminService.getDashboardStats()
    return {"total_users": 0, "total_events": 0, "total_articles": 0}


@router.get("/users", summary="List all users (ADMIN)")
async def list_users():
    # TODO: IUserRepository.findAll()
    return {"users": []}


@router.put("/users/{user_id}/role", summary="Change user role (ADMIN)")
async def update_user_role(user_id: str = Path(...), payload: UpdateRoleRequest = ...):
    # TODO: IUserService.updateRole(user_id, role)
    return {"message": f"Role updated to {payload.role}", "user_id": user_id}


@router.put("/users/{user_id}/block", summary="Block / unblock a user (ADMIN)")
async def toggle_block_user(user_id: str = Path(...)):
    # TODO: IUserService.blockUser(user_id)
    return {"message": "User block status toggled", "user_id": user_id}


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete user (ADMIN)")
async def admin_delete_user(user_id: str = Path(...)):
    # TODO: IUserService.deleteUser(user_id)
    return None


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Moderate / delete comment (ADMIN)")
async def admin_delete_comment(comment_id: str = Path(...)):
    # TODO: ICommentService.deleteComment(comment_id, force=True)
    return None


@router.post("/events/promote", status_code=status.HTTP_200_OK, summary="Promote an event to featured (ADMIN)")
async def promote_event(payload: PromoteEventRequest):
    # TODO: IEventService.promoteEvent(event_id)
    return {"message": "Event promoted", "event_id": payload.event_id}


@router.put("/articles/{article_id}/hide", summary="Hide / mask article from public (ADMIN)")
async def hide_article(article_id: str = Path(...)):
    # TODO: IArticleService.hideArticle(article_id)
    return {"message": "Article hidden", "article_id": article_id}


@router.post("/sources", status_code=status.HTTP_201_CREATED, summary="Add a new media source (ADMIN)")
async def create_source(payload: CreateSourceRequest):
    # TODO: ISourceRepository.save(payload)
    return {"message": "Source added", "name": payload.name}


@router.get("/stats", summary="System-wide analytics (ADMIN)")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns system-wide stats, including live ingestion funnel counts,
    media source split, topic distribution, and bias spectrum.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can access system stats"
        )
        
    from sqlalchemy import select, func
    from app.entities.models import Article, Event, Source, ProcessingStatus
    
    # 1. Ingestion Funnel Counts
    # The funnel is cumulative: each stage counts every article that reached it
    # OR went further. Counting only the exact current status makes the funnel
    # drain to zero as soon as the pipeline finishes, since a completed article
    # sits in PROCESSED and leaves all three earlier buckets. Stage order is
    # taken from the ProcessingStatus enum so added stages stay correct.
    pipeline_order = list(ProcessingStatus)

    async def count_reaching(stage: ProcessingStatus) -> int:
        reached = pipeline_order[pipeline_order.index(stage):]
        return await db.scalar(
            select(func.count(Article.id)).where(Article.processing_status.in_(reached))
        ) or 0

    scraped_count = await count_reaching(ProcessingStatus.SCRAPED)
    vectorized_count = await count_reaching(ProcessingStatus.EMBEDDED)
    clustered_count = await count_reaching(ProcessingStatus.CLUSTERED)
    enriched_count = await db.scalar(
        select(func.count(Event.id)).where(Event.status == "PROCESSED")
    ) or 0
    
    # 2. Media Source Split
    media_query = (
        select(Source.name, func.count(Article.id))
        .join(Article)
        .group_by(Source.name)
    )
    media_result = await db.execute(media_query)
    media_split = {row[0]: row[1] for row in media_result.all()}
    
    # 3. Topic Distribution
    topic_query = (
        select(Event.topic, func.count(Event.id))
        .where(Event.topic.isnot(None))
        .group_by(Event.topic)
    )
    topic_result = await db.execute(topic_query)
    topic_dist = {row[0]: row[1] for row in topic_result.all()}
    
    # 4. Bias Leaning Distribution
    bias_query = (
        select(Event.bias_lean, func.count(Event.id))
        .where(Event.bias_lean.isnot(None))
        .group_by(Event.bias_lean)
    )
    bias_result = await db.execute(bias_query)
    bias_dist = {row[0].name: row[1] for row in bias_result.all()}
    
    # Default values to satisfy empty data visualizations
    if not media_split:
        media_split = {"BBC News": 0, "CNN": 0, "Al Jazeera": 0}
        
    for topic in ["POLITICS", "ECONOMY", "TECHNOLOGY", "SPORTS", "HEALTH", "WORLD"]:
        if topic not in topic_dist:
            topic_dist[topic] = 0
            
    for bias in ["LEFT", "CENTER_LEFT", "CENTER", "CENTER_RIGHT", "RIGHT"]:
        if bias not in bias_dist:
            bias_dist[bias] = 0

    return {
        "funnel": {
            "scraped": scraped_count,
            "vectorized": vectorized_count,
            "clustered": clustered_count,
            "enriched": enriched_count
        },
        "media_split": media_split,
        "topic_distribution": topic_dist,
        "bias_distribution": bias_dist
    }


@router.post("/embed/process", status_code=status.HTTP_202_ACCEPTED, summary="Trigger batch article embedding process (ADMIN)")
async def process_embeddings(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """
    Trigger batch processing of article embeddings.
    Only users with the ADMIN role can execute this action.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can trigger the embedding pipeline"
        )
        
    embedding_service = EmbeddingService()
    background_tasks.add_task(embedding_service.process_scraped_batch)
    return {"status": "embedding_batch_initiated"}


@router.post("/cluster/process", status_code=status.HTTP_202_ACCEPTED, summary="Trigger batch article clustering process (ADMIN)")
async def process_clustering(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """
    Trigger batch processing of article clustering.
    Only users with the ADMIN role can execute this action.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can trigger the clustering pipeline"
        )
        
    clustering_service = ClusteringService()
    background_tasks.add_task(clustering_service.cluster_unassigned_articles)
    return {"status": "clustering_process_initiated"}


@router.post("/llm/process", status_code=status.HTTP_202_ACCEPTED, summary="Trigger batch LLM event intelligence processing (ADMIN)")
async def process_llm(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """
    Trigger batch processing of LLM event intelligence.
    Only users with the ADMIN role can execute this action.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can trigger the LLM processing pipeline"
        )
        
    from app.services.llm_service import LLMService
    llm_service = LLMService()
    background_tasks.add_task(llm_service.process_pending_events)
    return {"status": "llm_processing_initiated"}


@router.post("/search/sync", status_code=status.HTTP_202_ACCEPTED, summary="Trigger bulk search synchronization (ADMIN)")
async def sync_search_index(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """
    Trigger bulk synchronization of all PROCESSED events into Elasticsearch.
    Only users with the ADMIN role can execute this action.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can trigger search synchronization"
        )
        
    from app.services.search_service import SearchService
    search_service = SearchService()
    background_tasks.add_task(search_service.sync_all_processed_events)
    return {"status": "search_sync_initiated"}

