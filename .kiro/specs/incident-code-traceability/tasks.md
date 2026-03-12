# Implementation Plan: Incident-to-Code Traceability Platform

## Overview

This implementation plan builds a full-stack incident traceability platform that automatically correlates production incidents with code changes. The system integrates with existing GitHub, Jira, Linear, and Slack services to identify which commits, pull requests, and authors are responsible for production failures.

The implementation prioritizes the Diff_Engine as the critical component for comparing code versions and identifying changes that caused incidents. The backend uses Python/FastAPI with existing service patterns, and the frontend uses React/TypeScript with existing UI components.

## Tasks

- [x] 1. Set up database models and API infrastructure
  - Create SQLAlchemy models for incident analyses, repositories, error patterns, suspect commits, timeline events, and shareable reports
  - Add database migration script for new tables
  - Create Pydantic schemas for request/response validation
  - Set up FastAPI router for incident analysis endpoints
  - _Requirements: 3.1, 13.1, 16.6_

- [x] 2. Implement Diff_Engine (CRITICAL - Core functionality)
  - [x] 2.1 Create Diff_Engine service class with GitHub API integration
    - Implement `get_commit_diff(repo, commit_sha)` method using GitHub compare API
    - Implement `compare_commits(repo, base, head)` method for commit range diffs
    - Implement `format_unified_diff(diff)` to format diffs with line numbers
    - Implement `detect_file_renames(diff)` to identify renamed/moved files
    - Add error handling for invalid commits and API failures
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.7_
  
  - [x] 2.2 Write property test for Diff_Engine
    - **Property 1: Diff Engine Input Acceptance**
    - **Property 2: Diff Retrieval Completeness**
    - **Property 3: Unified Diff Format Compliance**
    - **Property 7: Diff Error Handling**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.7**
  
  - [x] 2.3 Add diff visualization support
    - Implement syntax highlighting detection by file extension
    - Add change type indicators (added/modified/deleted/renamed)
    - Format patch data with line number annotations
    - _Requirements: 1.4, 1.6, 6.4_

- [x] 3. Implement Repository_Connector enhancements
  - [x] 3.1 Extend existing GitHub service for incident analysis
    - Add `fetch_commits(repo, since, until)` method to retrieve commit history
    - Add `fetch_pull_request(repo, pr_number)` method for PR details
    - Add `get_commit_metadata(repo, sha)` method for commit info
    - Implement rate limit handling with exponential backoff
    - _Requirements: 2.1, 2.3, 2.4, 2.5, 2.6_
  
  - [x] 3.2 Create repository connection management
    - Add CRUD operations for repository connections in database
    - Implement secure credential storage with encryption
    - Add repository metadata caching (5-minute TTL)
    - _Requirements: 2.2, 2.7, 17.3_
  
  - [x] 3.3 Write unit tests for Repository_Connector
    - Test commit fetching with time windows
    - Test PR data retrieval and parsing
    - Test rate limit handling and retry logic
    - _Requirements: 2.3, 2.4, 2.6_

- [x] 4. Implement Incident_Analyzer for log parsing
  - [x] 4.1 Create log parser with multi-format support
    - Implement `parse_logs(log_content, format)` for JSON, syslog, and plain text
    - Implement `extract_error_patterns(parsed_log)` to identify errors
    - Implement `extract_stack_trace(log_content)` to parse stack traces
    - Extract file paths, function names, line numbers from stack traces
    - Extract timestamps from log entries
    - _Requirements: 4.1, 4.2, 4.3, 4.7_
  
  - [x] 4.2 Implement error normalization
    - Implement `normalize_error_message(error)` to remove variable values
    - Remove timestamps and dynamic data from error messages
    - Classify error types (exceptions, HTTP errors, DB errors)
    - _Requirements: 4.4, 4.5_
  
  - [x] 4.3 Write property test for error pattern extraction
    - **Property 16: Error Message Extraction**
    - **Property 17: Stack Trace Parsing**
    - **Property 18: Timestamp Extraction**
    - **Property 19: Error Normalization Consistency**
    - **Validate