"""
Repository Metadata Caching Service
Implements 5-minute TTL caching for repository metadata to reduce GitHub API calls
"""

import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
import threading


@dataclass
class RepositoryMetadata:
    """Repository metadata structure."""
    owner: str
    name: str
    default_branch: str
    description: Optional[str] = None
    language: Optional[str] = None
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    last_push: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class CacheEntry:
    """Cache entry with TTL."""
    data: RepositoryMetadata
    expires_at: datetime


class RepositoryCache:
    """
    In-memory cache for repository metadata with 5-minute TTL.
    Thread-safe implementation using locks.
    """
    
    def __init__(self, ttl_minutes: int = 5):
        self.ttl_minutes = ttl_minutes
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
    
    def _get_cache_key(self, owner: str, name: str) -> str:
        """Generate cache key for repository."""
        return f"{owner.lower()}/{name.lower()}"
    
    def _is_expired(self, entry: CacheEntry) -> bool:
        """Check if cache entry is expired."""
        return datetime.utcnow() >= entry.expires_at
    
    def _cleanup_expired(self) -> None:
        """Remove expired entries from cache."""
        current_time = datetime.utcnow()
        expired_keys = [
            key for key, entry in self._cache.items()
            if current_time >= entry.expires_at
        ]
        for key in expired_keys:
            del self._cache[key]
    
    def get(self, owner: str, name: str) -> Optional[RepositoryMetadata]:
        """
        Get repository metadata from cache.
        
        Args:
            owner: Repository owner
            name: Repository name
            
        Returns:
            RepositoryMetadata if found and not expired, None otherwise
        """
        with self._lock:
            self._cleanup_expired()
            
            cache_key = self._get_cache_key(owner, name)
            entry = self._cache.get(cache_key)
            
            if entry and not self._is_expired(entry):
                return entry.data
            
            # Remove expired entry
            if entry:
                del self._cache[cache_key]
            
            return None
    
    def set(self, metadata: RepositoryMetadata) -> None:
        """
        Store repository metadata in cache.
        
        Args:
            metadata: Repository metadata to cache
        """
        with self._lock:
            cache_key = self._get_cache_key(metadata.owner, metadata.name)
            expires_at = datetime.utcnow() + timedelta(minutes=self.ttl_minutes)
            
            self._cache[cache_key] = CacheEntry(
                data=metadata,
                expires_at=expires_at
            )
    
    def invalidate(self, owner: str, name: str) -> bool:
        """
        Remove repository metadata from cache.
        
        Args:
            owner: Repository owner
            name: Repository name
            
        Returns:
            True if entry was removed, False if not found
        """
        with self._lock:
            cache_key = self._get_cache_key(owner, name)
            if cache_key in self._cache:
                del self._cache[cache_key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()
    
    def size(self) -> int:
        """Get number of cached entries."""
        with self._lock:
            self._cleanup_expired()
            return len(self._cache)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            self._cleanup_expired()
            return {
                "total_entries": len(self._cache),
                "ttl_minutes": self.ttl_minutes,
                "entries": [
                    {
                        "key": key,
                        "expires_at": entry.expires_at.isoformat(),
                        "repository": f"{entry.data.owner}/{entry.data.name}"
                    }
                    for key, entry in self._cache.items()
                ]
            }


# Global cache instance
_repository_cache = RepositoryCache()


def get_cached_metadata(owner: str, name: str) -> Optional[RepositoryMetadata]:
    """Get repository metadata from cache."""
    return _repository_cache.get(owner, name)


def cache_metadata(metadata: RepositoryMetadata) -> None:
    """Cache repository metadata."""
    _repository_cache.set(metadata)


def invalidate_metadata(owner: str, name: str) -> bool:
    """Invalidate cached repository metadata."""
    return _repository_cache.invalidate(owner, name)


def clear_cache() -> None:
    """Clear all cached metadata."""
    _repository_cache.clear()


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    return _repository_cache.get_stats()