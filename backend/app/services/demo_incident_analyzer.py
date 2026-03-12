#!/usr/bin/env python3
"""
Demonstration script for the Incident Analyzer Service

This script shows how to use the IncidentAnalyzer to parse logs and extract error patterns.
"""

from incident_analyzer import IncidentAnalyzer
import json


def demo_python_error():
    """Demonstrate Python error analysis"""
    print("=== Python Error Analysis Demo ===")
    
    python_log = '''2024-01-15T14:30:25.123Z ERROR Application crashed during user authentication
Traceback (most recent call last):
  File "/app/services/auth_service.py", line 156, in authenticate_user
    user = database.get_user(user_id)
  File "/app/database/user_repository.py", line 89, in get_user
    return self.execute_query("SELECT * FROM users WHERE id = %s", [user_id])
  File "/app/database/connection.py", line 45, in execute_query
    cursor.execute(query, params)
ValueError: Invalid user ID format: 'abc123' - expected integer
2024-01-15T14:30:26.456Z INFO Attempting to recover from authentication error'''
    
    analyzer = IncidentAnalyzer()
    
    # Parse the logs
    parsed_log = analyzer.parse_logs(python_log, "plain")
    print(f"Parsed {len(parsed_log.entries)} log entries")
    
    # Extract error patterns
    patterns = analyzer.extract_error_patterns(parsed_log)
    print(f"Found {len(patterns)} error patterns")
    
    for i, pattern in enumerate(patterns, 1):
        print(f"\nError Pattern {i}:")
        print(f"  Type: {pattern.error_type}")
        print(f"  Message: {pattern.message}")
        print(f"  File Paths: {pattern.file_paths}")
        print(f"  Functions: {pattern.function_names}")
        print(f"  Line Numbers: {pattern.line_numbers}")
        print(f"  Timestamps: {pattern.timestamps}")


def demo_json_logs():
    """Demonstrate JSON log analysis"""
    print("\n=== JSON Log Analysis Demo ===")
    
    json_log = '''{"timestamp": "2024-01-15T14:30:25.123Z", "level": "ERROR", "message": "Database connection timeout", "service": "user-api", "timeout_ms": 30000}
{"timestamp": "2024-01-15T14:30:26.456Z", "level": "ERROR", "message": "HTTP Status 500: Internal Server Error", "endpoint": "/api/users/123", "response_time_ms": 5000}
{"timestamp": "2024-01-15T14:30:27.789Z", "level": "INFO", "message": "Retrying failed request", "service": "user-api", "retry_count": 1}'''
    
    analyzer = IncidentAnalyzer()
    
    # Parse JSON logs
    parsed_log = analyzer.parse_logs(json_log, "json")
    print(f"Parsed {len(parsed_log.entries)} JSON log entries")
    
    # Show parsed structure
    for i, entry in enumerate(parsed_log.entries, 1):
        print(f"\nEntry {i}:")
        print(f"  Timestamp: {entry.timestamp}")
        print(f"  Level: {entry.level}")
        print(f"  Message: {entry.message}")
        print(f"  Metadata: {entry.metadata}")
    
    # Extract error patterns
    patterns = analyzer.extract_error_patterns(parsed_log)
    print(f"\nFound {len(patterns)} error patterns:")
    
    for i, pattern in enumerate(patterns, 1):
        print(f"\nError Pattern {i}:")
        print(f"  Type: {pattern.error_type}")
        print(f"  Normalized Message: {pattern.message}")


def demo_syslog_format():
    """Demonstrate syslog format analysis"""
    print("\n=== Syslog Format Analysis Demo ===")
    
    syslog_content = '''Jan 15 14:30:25 web01 nginx: ERROR: upstream server timeout after 30s
Jan 15 14:30:26 web01 app: Exception in request handler: KeyError: 'user_id' not found in request
Jan 15 14:30:27 web01 app: INFO: Request completed with errors, returning 500'''
    
    analyzer = IncidentAnalyzer()
    
    # Parse syslog
    parsed_log = analyzer.parse_logs(syslog_content, "syslog")
    print(f"Parsed {len(parsed_log.entries)} syslog entries")
    
    # Show syslog structure
    for i, entry in enumerate(parsed_log.entries, 1):
        print(f"\nEntry {i}:")
        print(f"  Message: {entry.message}")
        print(f"  Hostname: {entry.metadata.get('hostname', 'N/A')}")
        print(f"  Tag: {entry.metadata.get('tag', 'N/A')}")
    
    # Extract error patterns
    patterns = analyzer.extract_error_patterns(parsed_log)
    print(f"\nFound {len(patterns)} error patterns:")
    
    for i, pattern in enumerate(patterns, 1):
        print(f"\nError Pattern {i}:")
        print(f"  Type: {pattern.error_type}")
        print(f"  Message: {pattern.message}")


def demo_stack_trace_extraction():
    """Demonstrate stack trace extraction capabilities"""
    print("\n=== Stack Trace Extraction Demo ===")
    
    # Test different programming languages
    test_cases = [
        ("Python", '''Traceback (most recent call last):
  File "/app/main.py", line 25, in main
    result = process_data()
  File "/app/processor.py", line 42, in process_data
    return calculate_result()
ValueError: Invalid input data'''),
        
        ("Java", '''Exception in thread "main" java.lang.NullPointerException
    at com.example.service.DataProcessor.processData(DataProcessor.java:156)
    at com.example.Main.main(Main.java:23)'''),
        
        ("JavaScript", '''Error: Cannot read property 'length' of undefined
    at processArray (/app/utils.js:45:12)
    at main (/app/index.js:23:5)''')
    ]
    
    analyzer = IncidentAnalyzer()
    
    for language, stack_trace in test_cases:
        print(f"\n{language} Stack Trace:")
        extracted = analyzer.extract_stack_trace(stack_trace)
        
        print(f"  File Paths: {extracted.file_paths}")
        print(f"  Functions: {extracted.function_names}")
        print(f"  Line Numbers: {extracted.line_numbers}")


def demo_error_normalization():
    """Demonstrate error message normalization"""
    print("\n=== Error Message Normalization Demo ===")
    
    analyzer = IncidentAnalyzer()
    
    test_messages = [
        "Connection failed to 192.168.1.100:5432 at 2024-01-15T14:30:25Z with ID 12345",
        "Connection failed to 10.0.0.1:3306 at 2024-02-20T09:15:30Z with ID 67890",
        "Failed to process request 550e8400-e29b-41d4-a716-446655440000",
        "Failed to process request 123e4567-e89b-12d3-a456-426614174000",
        "User john.doe@example.com not found in system",
        "User jane.smith@company.org not found in system"
    ]
    
    print("Original vs Normalized Messages:")
    for msg in test_messages:
        normalized = analyzer._normalize_error_message(msg)
        print(f"  Original:   {msg}")
        print(f"  Normalized: {normalized}")
        print()


if __name__ == "__main__":
    print("Incident Analyzer Service Demonstration")
    print("=" * 50)
    
    demo_python_error()
    demo_json_logs()
    demo_syslog_format()
    demo_stack_trace_extraction()
    demo_error_normalization()
    
    print("\n" + "=" * 50)
    print("Demo completed successfully!")