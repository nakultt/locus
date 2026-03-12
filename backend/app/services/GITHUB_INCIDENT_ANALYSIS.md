# GitHub Incident Analysis Extensions

This document describes the new GitHub service extensions added for incident-to-code traceability.

## New Methods Added

### 1. `fetch_commits(repo, since, until)`

**Purpose:** Retrieve commit history within a specific time range for incident correlation.

**Parameters:**
- `owner`: Repository owner (username or organization)
- `repo`: Repository name
- `since`: ISO 8601 timestamp to fetch commits since
- `until`: ISO 8601 timestamp to fetch commits until
- `per_page`: Number of commits per page (default: 100, max: 100)

**Returns:** Formatted string with commit information including SHA, message, author, and file changes.

**Example Usage:**
```python
result = github_fetch_commits(
    owner="myorg",
    repo="myrepo",
    since="2024-01-01T00:00:00Z",
    until="2024-01-31T23:59:59Z"
)
```

### 2. `fetch_pull_request(repo, pr_number)`

**Purpose:** Get detailed pull request information including reviewers, linked issues, and merge status.

**Parameters:**
- `owner`: Repository owner
- `repo`: Repository name
- `pr_number`: Pull request number

**Returns:** Formatted string with comprehensive PR details including:
- Title, author, and state
- Branch information (head → base)
- Merge status and timestamp
- Reviewers list
- Linked issues (extracted from PR body)
- Creation and update timestamps

**Example Usage:**
```python
result = github_fetch_pull_request(
    owner="myorg",
    repo="myrepo",
    pr_number=123
)
```

### 3. `get_commit_metadata(repo, sha)`

**Purpose:** Get detailed commit metadata including author, stats, and changed files.

**Parameters:**
- `owner`: Repository owner
- `repo`: Repository name
- `sha`: Commit SHA

**Returns:** Formatted string with detailed commit information including:
- Commit message and SHA
- Author and committer details
- File change statistics (additions, deletions, total)
- List of changed files with status indicators
- Associated pull request (if found)

**Example Usage:**
```python
result = github_get_commit_metadata(
    owner="myorg",
    repo="myrepo",
    sha="abc123def456789"
)
```

## Rate Limiting and Error Handling

### Exponential Backoff

All new methods implement rate limit handling with exponential backoff:

- **Initial retry delay:** 1 second (2^0)
- **Second retry delay:** 2 seconds (2^1)
- **Third retry delay:** 4 seconds (2^2)
- **Maximum retries:** 3 attempts

### Error Handling

The service provides comprehensive error handling:

1. **Authentication errors:** Clear messages when GitHub token is missing or invalid
2. **Rate limit errors:** Automatic retry with exponential backoff
3. **API errors:** Descriptive error messages with HTTP status codes
4. **Network errors:** Graceful handling of connection issues

## Integration with Incident Analysis

These methods support the incident-to-code traceability workflow:

1. **Commit History Retrieval:** `fetch_commits` gets recent commits for correlation with incident timestamps
2. **Pull Request Context:** `fetch_pull_request` provides business context through linked issues and reviewers
3. **Detailed Analysis:** `get_commit_metadata` gives comprehensive commit details for root cause analysis

## Requirements Validation

This implementation validates the following requirements:

- **Requirement 2.1:** GitHub authentication with OAuth/PAT ✅
- **Requirement 2.3:** Fetch commit history for past 30 days ✅
- **Requirement 2.4:** Retrieve PR information with linked issues ✅
- **Requirement 2.5:** Extract commit metadata ✅
- **Requirement 2.6:** Rate limit handling with exponential backoff ✅

## Testing

The implementation includes comprehensive unit tests covering:

- Successful API responses
- Error conditions (404, rate limits, authentication)
- Rate limit handling with exponential backoff
- Edge cases (empty results, malformed data)

Run tests with:
```bash
python -m pytest backend/app/services/test_github_incident_analysis.py -v
```

## Tool Integration

The new methods are automatically included in the GitHub tools collection:

```python
from backend.app.services.github import get_github_tools

tools = get_github_tools("your_github_token")
# tools now includes the 3 new incident analysis tools
```

Total tools available: **15** (12 existing + 3 new incident analysis tools)