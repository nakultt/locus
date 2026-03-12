"""
Integration tests for Incident Analyzer Service

These tests demonstrate the complete workflow from log parsing to error pattern extraction.
"""

import pytest
from backend.app.services.incident_analyzer import IncidentAnalyzer


class TestIncidentAnalyzerIntegration:
    """Integration tests for complete incident analysis workflow"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.analyzer = IncidentAnalyzer()

    def test_complete_python_error_analysis(self):
        """Test complete analysis of Python error logs"""
        python_log = '''2024-01-15T14:30:25.123Z ERROR Application crashed
Traceback (most recent call last):
  File "/app/services/user_service.py", line 156, in get_user_profile
    profile = database.fetch_profile(user_id)
  File "/app/database/connection.py", line 89, in fetch_profile
    return self.execute_query(query, params)
  File "/app/database/connection.py", line 45, in execute_query
    cursor.execute(query, params)
ValueError: Invalid user ID format: abc123
2024-01-15T14:30:26.456Z INFO Attempting recovery'''
        
        # Parse logs
        parsed_log = self.analyzer.parse_logs(python_log, "plain")
        assert len(parsed_log.entries) >= 3  # Multiple entries due to multi-line stack trace
        
        # Extract error patterns
        patterns = self.analyzer.extract_error_patterns(parsed_log)
        assert len(patterns) >= 1
        
        # Find the main error pattern
        main_pattern = max(patterns, key=lambda p: len(p.file_paths) + len(p.function_names))
        
        # Verify error pattern details
        assert main_pattern.error_type == "exception"
        assert "ValueError" in main_pattern.message or "Application crashed" in main_pattern.message
        
        # Verify stack trace extraction
        assert len(main_pattern.file_paths) >= 2
        assert "/app/services/user_service.py" in main_pattern.file_paths
        assert "/app/database/connection.py" in main_pattern.file_paths
        
        assert len(main_pattern.function_names) >= 2
        assert "get_user_profile" in main_pattern.function_names
        assert "fetch_profile" in main_pattern.function_names
        
        assert len(main_pattern.line_numbers) >= 2
        assert 156 in main_pattern.line_numbers
        assert 89 in main_pattern.line_numbers
        
        # Verify timestamp extraction
        assert len(main_pattern.timestamps) >= 1
        assert main_pattern.timestamps[0] is not None

    def test_complete_java_error_analysis(self):
        """Test complete analysis of Java error logs"""
        java_log = '''2024-01-15 14:30:25 ERROR [main] Application startup failed
Exception in thread "main" java.lang.NullPointerException: Cannot invoke method on null object
    at com.example.service.UserService.validateUser(UserService.java:142)
    at com.example.controller.AuthController.login(AuthController.java:67)
    at com.example.Main.main(Main.java:23)
2024-01-15 14:30:26 INFO [main] Shutting down application'''
        
        # Parse logs
        parsed_log = self.analyzer.parse_logs(java_log, "plain")
        assert len(parsed_log.entries) >= 2
        
        # Extract error patterns
        patterns = self.analyzer.extract_error_patterns(parsed_log)
        assert len(patterns) >= 1
        
        # Find the main error pattern
        main_pattern = max(patterns, key=lambda p: len(p.file_paths) + len(p.function_names))
        
        # Verify error pattern details
        assert main_pattern.error_type == "exception"
        assert "NullPointerException" in main_pattern.message or "startup failed" in main_pattern.message
        
        # Verify stack trace extraction
        assert len(main_pattern.file_paths) >= 1
        assert any("UserService.java" in path for path in main_pattern.file_paths)
        
        assert len(main_pattern.function_names) >= 1
        assert "validateUser" in main_pattern.function_names or "login" in main_pattern.function_names
        
        assert len(main_pattern.line_numbers) >= 1
        assert 142 in main_pattern.line_numbers or 67 in main_pattern.line_numbers

    def test_complete_json_log_analysis(self):
        """Test complete analysis of JSON format logs"""
        json_log = '''{"timestamp": "2024-01-15T14:30:25.123Z", "level": "ERROR", "message": "Database connection timeout", "service": "user-api"}
{"timestamp": "2024-01-15T14:30:26.456Z", "level": "ERROR", "message": "HTTP Status 500: Internal Server Error", "endpoint": "/api/users"}
{"timestamp": "2024-01-15T14:30:27.789Z", "level": "INFO", "message": "Retrying connection", "service": "user-api"}'''
        
        # Parse logs
        parsed_log = self.analyzer.parse_logs(json_log, "json")
        assert len(parsed_log.entries) == 3
        assert parsed_log.format == "json"
        
        # Verify JSON parsing preserved structure
        for entry in parsed_log.entries:
            assert entry.timestamp is not None
            assert entry.level in ["ERROR", "INFO"]
            assert isinstance(entry.metadata, dict)
        
        # Extract error patterns
        patterns = self.analyzer.extract_error_patterns(parsed_log)
        assert len(patterns) == 2  # Two ERROR entries
        
        # Verify error types
        error_types = [p.error_type for p in patterns]
        assert "database_error" in error_types or "timeout_error" in error_types
        assert "http_error" in error_types
        
        # Verify timestamps were extracted
        for pattern in patterns:
            assert len(pattern.timestamps) == 1
            assert pattern.timestamps[0] is not None

    def test_complete_syslog_analysis(self):
        """Test complete analysis of syslog format logs"""
        syslog_content = '''Jan 15 14:30:25 web01 nginx: ERROR: Connection timeout to upstream server
Jan 15 14:30:26 web01 app: Exception in request handler: KeyError: 'user_id'
Jan 15 14:30:27 web01 app: INFO: Request completed with errors'''
        
        # Parse logs
        parsed_log = self.analyzer.parse_logs(syslog_content, "syslog")
        assert len(parsed_log.entries) == 3
        assert parsed_log.format == "syslog"
        
        # Verify syslog parsing preserved metadata
        for entry in parsed_log.entries:
            assert 'hostname' in entry.metadata
            assert 'tag' in entry.metadata
            assert entry.metadata['hostname'] == 'web01'
        
        # Extract error patterns
        patterns = self.analyzer.extract_error_patterns(parsed_log)
        assert len(patterns) >= 1
        
        # Verify error types
        error_types = [p.error_type for p in patterns]
        assert "timeout_error" in error_types or "exception" in error_types

    def test_mixed_error_types_analysis(self):
        """Test analysis of logs with multiple error types"""
        mixed_log = '''2024-01-15 14:30:25 ERROR HTTP Status 404: User not found
2024-01-15 14:30:26 ERROR Database connection failed: timeout after 30s
2024-01-15 14:30:27 ERROR OutOfMemoryError: Java heap space exceeded
2024-01-15 14:30:28 ERROR Exception in thread "worker-1": NullPointerException'''
        
        # Parse and analyze
        parsed_log = self.analyzer.parse_logs(mixed_log, "plain")
        patterns = self.analyzer.extract_error_patterns(parsed_log)
        
        # Should identify multiple error types
        assert len(patterns) >= 3
        
        error_types = [p.error_type for p in patterns]
        assert "http_error" in error_types
        assert "database_error" in error_types or "timeout_error" in error_types
        assert "memory_error" in error_types
        assert "exception" in error_types
        
        # Verify normalization worked
        for pattern in patterns:
            normalized_msg = pattern.message
            assert "[TIMESTAMP]" in normalized_msg or "[NUMBER]" in normalized_msg

    def test_no_errors_in_log(self):
        """Test analysis of logs with no errors"""
        info_log = '''2024-01-15 14:30:25 INFO Application started successfully
2024-01-15 14:30:26 DEBUG Processing user request
2024-01-15 14:30:27 INFO Request completed successfully'''
        
        # Parse and analyze
        parsed_log = self.analyzer.parse_logs(info_log, "plain")
        patterns = self.analyzer.extract_error_patterns(parsed_log)
        
        # Should find no error patterns
        assert len(patterns) == 0

    def test_malformed_log_handling(self):
        """Test handling of malformed or mixed format logs"""
        malformed_log = '''{"timestamp": "2024-01-15T14:30:25Z", "level": "ERROR"
This is not JSON but contains ERROR: Something went wrong
Jan 15 14:30:27 server01 app: Another error occurred
Regular text with Exception: ValueError'''
        
        # Should handle mixed formats gracefully
        parsed_log = self.analyzer.parse_logs(malformed_log, "json")
        assert len(parsed_log.entries) >= 3
        
        patterns = self.analyzer.extract_error_patterns(parsed_log)
        assert len(patterns) >= 2  # Should find multiple errors despite format issues


if __name__ == "__main__":
    pytest.main([__file__])