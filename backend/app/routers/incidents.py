"""
Incident Analysis Router
Endpoints for incident log analysis and code traceability
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
import uuid
from datetime import datetime

from app import schemas, crud, security
from app.database import get_db
from app.models import (
    IncidentAnalysis,
    Repository,
    AnalysisRepository,
    ErrorPattern,
    SuspectCommit,
    TimelineEvent,
    ShareableReport,
    User
)
from app.services.github import fetch_repository_metadata
from app.services.repository_cache import get_cache_stats

router = APIRouter()


@router.post(
    "/repositories",
    response_model=schemas.RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Connect a GitHub repository"
)
async def create_repository(
    repository: schemas.RepositoryCreate,
    user_id: int,
    db: Session = Depends(get_db)
) -> schemas.RepositoryResponse:
    """
    Connect a GitHub repository for incident analysis.
    
    - **owner**: Repository owner/organization
    - **name**: Repository name
    - **default_branch**: Default branch name (default: main)
    - **github_token**: GitHub personal access token (optional, encrypted)
    """
    try:
        # Use CRUD operation with proper encryption
        db_repository = crud.create_repository(
            db=db,
            user_id=user_id,
            owner=repository.owner,
            name=repository.name,
            default_branch=repository.default_branch,
            github_token=repository.github_token
        )
        
        # Fetch and cache repository metadata if token provided
        if repository.github_token:
            try:
                metadata, error = fetch_repository_metadata(
                    repository.owner, 
                    repository.name, 
                    repository.github_token
                )
                if error:
                    # Log warning but don't fail the creation
                    print(f"Warning: Could not fetch metadata for {repository.owner}/{repository.name}: {error}")
            except Exception as e:
                # Log warning but don't fail the creation
                print(f"Warning: Exception fetching metadata for {repository.owner}/{repository.name}: {str(e)}")
        
        return schemas.RepositoryResponse.model_validate(db_repository)
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create repository: {str(e)}"
        )


@router.get(
    "/repositories",
    response_model=list[schemas.RepositoryResponse],
    summary="List connected repositories"
)
async def list_repositories(
    user_id: int,
    db: Session = Depends(get_db)
) -> list[schemas.RepositoryResponse]:
    """
    Get list of all connected repositories for a user.
    """
    try:
        repositories = crud.get_user_repositories(db, user_id)
        return [schemas.RepositoryResponse.model_validate(r) for r in repositories]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list repositories: {str(e)}"
        )


@router.get(
    "/repositories/{repository_id}",
    response_model=schemas.RepositoryResponse,
    summary="Get repository details"
)
async def get_repository(
    repository_id: int,
    user_id: int,
    db: Session = Depends(get_db)
) -> schemas.RepositoryResponse:
    """
    Get details of a specific repository.
    """
    repository = crud.get_repository_by_id(db, user_id, repository_id)
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found"
        )
    
    return schemas.RepositoryResponse.model_validate(repository)


@router.put(
    "/repositories/{repository_id}",
    response_model=schemas.RepositoryResponse,
    summary="Update repository details"
)
async def update_repository(
    repository_id: int,
    user_id: int,
    repository_update: schemas.RepositoryCreate,
    db: Session = Depends(get_db)
) -> schemas.RepositoryResponse:
    """
    Update repository details including GitHub token.
    """
    try:
        updated_repository = crud.update_repository(
            db=db,
            user_id=user_id,
            repository_id=repository_id,
            default_branch=repository_update.default_branch,
            github_token=repository_update.github_token
        )
        
        if not updated_repository:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Repository not found"
            )
        
        # Invalidate cache when repository is updated
        from app.services.repository_cache import invalidate_metadata
        invalidate_metadata(updated_repository.owner, updated_repository.name)
        
        return schemas.RepositoryResponse.model_validate(updated_repository)
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update repository: {str(e)}"
        )


@router.delete(
    "/repositories/{repository_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect a repository"
)
async def delete_repository(
    repository_id: int,
    user_id: int,
    db: Session = Depends(get_db)
) -> None:
    """
    Disconnect a repository from the system.
    """
    # Get repository info before deletion for cache invalidation
    repository = crud.get_repository_by_id(db, user_id, repository_id)
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found"
        )
    
    # Delete repository
    success = crud.delete_repository(db, user_id, repository_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found"
        )
    
    # Invalidate cache
    from app.services.repository_cache import invalidate_metadata
    invalidate_metadata(repository.owner, repository.name)


@router.get(
    "/cache/stats",
    summary="Get repository cache statistics"
)
async def get_cache_statistics() -> dict:
    """
    Get repository metadata cache statistics.
    """
    return get_cache_stats()


@router.post(
    "/analyze",
    response_model=schemas.IncidentAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new incident analysis"
)
async def create_incident_analysis(
    analysis: schemas.IncidentAnalysisCreate,
    user_id: int,
    db: Session = Depends(get_db)
) -> schemas.IncidentAnalysisResponse:
    """
    Create a new incident analysis from log content.
    
    - **log_content**: The incident log content to analyze
    - **log_format**: Optional log format (json, plain, syslog)
    - **repository_ids**: List of repository IDs to analyze against
    """
    # Validate user exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Validate repositories exist and belong to user using CRUD
    if analysis.repository_ids:
        valid_repos = []
        for repo_id in analysis.repository_ids:
            repo = crud.get_repository_by_id(db, user_id, repo_id)
            if not repo:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Repository with ID {repo_id} not found or not accessible"
                )
            valid_repos.append(repo)
    
    # Create incident analysis
    db_analysis = IncidentAnalysis(
        user_id=user_id,
        analysis_uuid=str(uuid.uuid4()),
        log_content=analysis.log_content,
        log_format=analysis.log_format,
        status="pending"
    )
    db.add(db_analysis)
    db.flush()
    
    # Link repositories
    for repo_id in analysis.repository_ids:
        analysis_repo = AnalysisRepository(
            analysis_id=db_analysis.id,
            repository_id=repo_id
        )
        db.add(analysis_repo)
    
    db.commit()
    db.refresh(db_analysis)
    
    # Build response
    return _build_analysis_response(db, db_analysis)


@router.get(
    "/history",
    response_model=schemas.IncidentAnalysisListResponse,
    summary="Get incident analysis history"
)
async def get_incident_history(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
) -> schemas.IncidentAnalysisListResponse:
    """
    Get paginated list of incident analyses for a user.
    
    - **limit**: Maximum number of results (default: 50)
    - **offset**: Number of results to skip (default: 0)
    """
    # Validate user exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Get total count
    total = db.query(IncidentAnalysis).filter(
        IncidentAnalysis.user_id == user_id
    ).count()
    
    # Get analyses
    analyses = db.query(IncidentAnalysis).filter(
        IncidentAnalysis.user_id == user_id
    ).order_by(IncidentAnalysis.created_at.desc()).limit(limit).offset(offset).all()
    
    # Build list items
    items = []
    for analysis in analyses:
        error_count = db.query(ErrorPattern).filter(
            ErrorPattern.analysis_id == analysis.id
        ).count()
        
        suspect_count = db.query(SuspectCommit).filter(
            SuspectCommit.analysis_id == analysis.id
        ).count()
        
        items.append(schemas.IncidentAnalysisListItem(
            id=analysis.id,
            analysis_uuid=analysis.analysis_uuid,
            status=analysis.status,
            created_at=analysis.created_at,
            completed_at=analysis.completed_at,
            error_count=error_count,
            suspect_commit_count=suspect_count
        ))
    
    return schemas.IncidentAnalysisListResponse(
        analyses=items,
        total=total
    )


@router.get(
    "/history",
    response_model=schemas.IncidentAnalysisListResponse,
    summary="Get incident analysis history"
)
async def get_incident_history(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
) -> schemas.IncidentAnalysisListResponse:
    """
    Get paginated list of incident analyses for a user.
    
    - **limit**: Maximum number of results (default: 50)
    - **offset**: Number of results to skip (default: 0)
    """
    # Validate user exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Get total count
    total = db.query(IncidentAnalysis).filter(
        IncidentAnalysis.user_id == user_id
    ).count()
    
    # Get analyses
    analyses = db.query(IncidentAnalysis).filter(
        IncidentAnalysis.user_id == user_id
    ).order_by(IncidentAnalysis.created_at.desc()).limit(limit).offset(offset).all()
    
    # Build list items
    items = []
    for analysis in analyses:
        error_count = db.query(ErrorPattern).filter(
            ErrorPattern.analysis_id == analysis.id
        ).count()
        
        suspect_count = db.query(SuspectCommit).filter(
            SuspectCommit.analysis_id == analysis.id
        ).count()
        
        items.append(schemas.IncidentAnalysisListItem(
            id=analysis.id,
            analysis_uuid=analysis.analysis_uuid,
            status=analysis.status,
            created_at=analysis.created_at,
            completed_at=analysis.completed_at,
            error_count=error_count,
            suspect_commit_count=suspect_count
        ))
    
    return schemas.IncidentAnalysisListResponse(
        analyses=items,
        total=total
    )


@router.get(
    "/{analysis_id}",
    response_model=schemas.IncidentAnalysisResponse,
    summary="Get incident analysis details"
)
async def get_incident_analysis(
    analysis_id: int,
    user_id: int,
    db: Session = Depends(get_db)
) -> schemas.IncidentAnalysisResponse:
    """
    Get detailed information about a specific incident analysis.
    
    Returns the analysis with all error patterns, suspect commits, and timeline events.
    """
    # Get analysis
    analysis = db.query(IncidentAnalysis).filter(
        IncidentAnalysis.id == analysis_id,
        IncidentAnalysis.user_id == user_id
    ).first()
    
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incident analysis not found"
        )
    
    return _build_analysis_response(db, analysis)


def _build_analysis_response(
    db: Session,
    analysis: IncidentAnalysis
) -> schemas.IncidentAnalysisResponse:
    """Helper function to build complete analysis response."""
    # Get error patterns
    error_patterns = db.query(ErrorPattern).filter(
        ErrorPattern.analysis_id == analysis.id
    ).all()
    
    # Get suspect commits with repositories
    suspect_commits = db.query(SuspectCommit).filter(
        SuspectCommit.analysis_id == analysis.id
    ).all()
    
    # Get timeline events
    timeline_events = db.query(TimelineEvent).filter(
        TimelineEvent.analysis_id == analysis.id
    ).order_by(TimelineEvent.timestamp).all()
    
    # Get shareable reports
    shareable_reports = db.query(ShareableReport).filter(
        ShareableReport.analysis_id == analysis.id
    ).all()
    
    # Get linked repositories
    analysis_repos = db.query(AnalysisRepository).filter(
        AnalysisRepository.analysis_id == analysis.id
    ).all()
    
    repositories = [
        db.query(Repository).filter(Repository.id == ar.repository_id).first()
        for ar in analysis_repos
    ]
    
    # Parse JSON fields for error patterns
    import json
    error_pattern_responses = []
    for ep in error_patterns:
        error_pattern_responses.append(schemas.ErrorPatternResponse(
            id=ep.id,
            error_type=ep.error_type,
            message=ep.message,
            file_paths=json.loads(ep.file_paths) if ep.file_paths else None,
            function_names=json.loads(ep.function_names) if ep.function_names else None,
            line_numbers=json.loads(ep.line_numbers) if ep.line_numbers else None,
            timestamps=json.loads(ep.timestamps) if ep.timestamps else None,
            raw_stack_trace=ep.raw_stack_trace
        ))
    
    # Parse JSON fields for suspect commits
    suspect_commit_responses = []
    for sc in suspect_commits:
        repo = db.query(Repository).filter(Repository.id == sc.repository_id).first()
        suspect_commit_responses.append(schemas.SuspectCommitResponse(
            id=sc.id,
            commit_sha=sc.commit_sha,
            author_name=sc.author_name,
            author_email=sc.author_email,
            commit_message=sc.commit_message,
            commit_timestamp=sc.commit_timestamp,
            confidence_score=sc.confidence_score,
            matching_files=json.loads(sc.matching_files) if sc.matching_files else None,
            matching_functions=json.loads(sc.matching_functions) if sc.matching_functions else None,
            pr_number=sc.pr_number,
            pr_title=sc.pr_title,
            repository=schemas.RepositoryResponse.model_validate(repo)
        ))
    
    # Parse JSON fields for timeline events
    timeline_event_responses = []
    for te in timeline_events:
        timeline_event_responses.append(schemas.TimelineEventResponse(
            id=te.id,
            timestamp=te.timestamp,
            event_type=te.event_type,
            title=te.title,
            description=te.description,
            event_metadata=json.loads(te.event_metadata) if te.event_metadata else None
        ))
    
    return schemas.IncidentAnalysisResponse(
        id=analysis.id,
        analysis_uuid=analysis.analysis_uuid,
        log_content=analysis.log_content,
        log_format=analysis.log_format,
        status=analysis.status,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
        error_patterns=error_pattern_responses,
        suspect_commits=suspect_commit_responses,
        timeline_events=timeline_event_responses,
        shareable_reports=[schemas.ShareableReportResponse.model_validate(sr) for sr in shareable_reports],
        repositories=[schemas.RepositoryResponse.model_validate(r) for r in repositories if r]
    )
