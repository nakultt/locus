"""
Unit tests for Incident Analyzer Service
"""

import pytest
import json
from datetime import datetime
from backend.app.services.incident_analyzer import (
    IncidentAnalyzer, 
    LogFormat, 
    ErrorPattern, 
    LogEntry, 
    ParsedLog, 
    StackTrace
)


class TestIncidentAnalyzer:
    """Test suite for IncidentAnalyzer"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.analyzer = IncidentAnalyzer()
    
    def test_parse_logs_json_format(self):
        """Test parsing JSON format logs"""
        json_log = '''{"timestamp": "2024-01-15T14:30:25.123Z", "level": "ERROR", "message": "Database connection failed"}
{"timestamp": "2024-01-15T14:30:26.456Z", "level": "INFO", "message": "Retrying connection"}'''
        
        result = self.analyzer.parse_logs(json_log, "json")
        
        assert result.format == "json"
        assert len(result.entries) == 2
        assert result.entries[0].level == "ERROR"
        assert result.entries[0].message == "Database connection failed"
        assert result.entries[0].timestamp is not None
        assert result.metadata['total_entries'] == 2
    
    def test_parse_logs_syslog_format(self):
        """Test parsing syslog format logs"""
        syslog_content = '''Jan 15 14:30:25 server01 myapp: ERROR: Connection timeout
Jan 15 14:30:26 server01 myapp: INFO: Retrying connection'''
        
        result = self.analyzer.parse_logs(syslog_content, "syslog")
        
        assert result.format == "syslog"
        assert len(result.entries) == 2
        assert result.entries[0].message == "ERROR: Connection timeout"
        assert result.entries[0].metadata['hostname'] == "server01"
        assert result.entries[0].metadata['tag'] == "myapp"
    
    def test_parse_logs_plain_format(self):
        """Test parsing plain text logs"""
        plain_log = '''2024-01-15 14:30:25 ERROR Database connection failed
2024-01-15 14:30:26 INFO Retrying connection'''
        
        result = self.analyzer.parse_logs(plain_log, "plain")
        
        assert result.format == "plain"
        assert len(result.entries) == 2
        assert result.entries[0].level == "ERROR"
        assert result.entries[0].timestamp is not None
    
    def test_parse_logs_empty_content(self):
        """Test parsing empty log content raises ValueError"""
        with pytest.raises(ValueError, match="Log content cannot be empty"):
            self.analyzer.parse_logs("", "json")
        
        with pytest.raises(ValueError, match="Log content cannot be empty"):
            self.analyzer.parse_logs("   ", "plain")
    
    def test_extract_error_patterns_with_exceptions(self):
        """Test extracting error patterns from logs with exceptions"""
        log_content = '''2024-01-15 14:30:25 ERROR Exception in thread "main" java.lang.NullPointerException
    at com.example.MyClass.myMethod(MyClass.java:42)
    at com.example.Main.main(Main.java:15)'''
        
        parsed_log = self.analyzer.parse_logs(log_content, "plain")
        patterns = self.analyzer.extract_error_patterns(parsed_log)
        
        assert len(patterns) >= 1
        # Find the pattern with the most information
        main_pattern = max(patterns, key=lambda p: len(p.file_paths) + len(p.function_names))
        assert main_pattern.error_type == "exception"
        assert "java.lang.NullPointerException" in main_pattern.message
        assert len(main_pattern.file_paths) >= 1
        assert len(main_pattern.function_names) >= 1
        assert len(main_pattern.line_numbers) >= 1
    
    def test_extract_error_patterns_with_http_errors(self):
        """Test extracting HTTP error patterns"""
        log_content = '''2024-01-15 14:30:25 ERROR HTTP Status 500: Internal Server Error'''
        
        parsed_log = self.analyzer.parse_logs(log_content, "plain")
        patterns = self.analyzer.extract_error_patterns(parsed_log)
        
        assert len(patterns) == 1
        assert patterns[0].error_type == "http_error"
    
    def test_extract_stack_trace_python(self):
        """Test extracting Python stack trace"""
        log_content = '''Traceback (most recent call last):
  File "/app/main.py", line 25, in main
    result = process_data()
  File "/app/processor.py", line 42, in process_data
    return calculate_result()
ValueError: Invalid input data'''
        
        stack_trace = self.analyzer.extract_stack_trace(log_content)
        
        assert len(stack_trace.file_paths) == 2
        assert "/app/main.py" in stack_trace.file_paths
        assert "/app/processor.py" in stack_trace.file_paths
        assert len(stack_trace.function_names) == 2
        assert "main" in stack_trace.function_names
        assert "process_data" in stack_trace.function_names
        assert len(stack_trace.line_numbers) == 2
        assert 25 in stack_trace.line_numbers
        assert 42 in stack_trace.line_numbers
    
    def test_extract_stack_trace_java(self):
        """Test extracting Java stack trace"""
        log_content = '''Exception in thread "main" java.lang.NullPointerException
    at com.example.service.DataProcessor.processData(DataProcessor.java:156)
    at com.example.Main.main(Main.java:23)'''
        
        stack_trace = self.analyzer.extract_stack_trace(log_content)
        
        assert len(stack_trace.file_paths) >= 1
        assert "com/example/service/DataProcessor.java" in stack_trace.file_paths
        assert len(stack_trace.function_names) >= 1
        assert "processData" in stack_trace.function_names
        assert len(stack_trace.line_numbers) >= 1
        assert 156 in stack_trace.line_numbers
    
    def test_extract_stack_trace_javascript(self):
        """Test extracting JavaScript stack trace"""
        log_content = '''Error: Cannot read property 'length' of undefined
    at processArray (/app/utils.js:45:12)
    at main (/app/index.js:23:5)'''
        
        stack_trace = self.analyzer.extract_stack_trace(log_content)
        
        assert len(stack_trace.file_paths) >= 1
        assert "/app/utils.js" in stack_trace.file_paths
        assert len(stack_trace.function_names) >= 1
        assert "processArray" in stack_trace.function_names
        assert len(stack_trace.line_numbers) >= 1
        assert 45 in stack_trace.line_numbers
    
    def test_extract_stack_trace_no_trace(self):
        """Test extracting stack trace when none exists"""
        log_content = '''2024-01-15 14:30:25 INFO Application started successfully'''
        
        stack_trace = self.analyzer.extract_stack_trace(log_content)
        
        assert len(stack_trace.file_paths) == 0
        assert len(stack_trace.function_names) == 0
        assert len(stack_trace.line_numbers) == 0
        assert stack_trace.raw_trace == log_content
    
    def test_timestamp_extraction_iso8601(self):
        """Test extracting ISO 8601 timestamps"""
        text = "2024-01-15T14:30:25.123Z ERROR Something went wrong"
        timestamp = self.analyzer._extract_timestamp_from_text(text)
        
        assert timestamp is not None
        assert timestamp.year == 2024
        assert timestamp.month == 1
        assert timestamp.day == 15
    
    def test_timestamp_extraction_syslog(self):
        """Test extracting syslog format timestamps"""
        text = "Jan 15 14:30:25 server01 myapp: ERROR Something went wrong"
        timestamp = self.analyzer._extract_timestamp_from_text(text)
        
        assert timestamp is not None
        assert timestamp.month == 1
        assert timestamp.day == 15
        assert timestamp.hour == 14
        assert timestamp.minute == 30
        assert timestamp.second == 25
    
    def test_timestamp_extraction_unix(self):
        """Test extracting Unix timestamps"""
        text = "1705327825 ERROR Something went wrong"
        timestamp = self.analyzer._extract_timestamp_from_text(text)
        
        assert timestamp is not None
    
    def test_timestamp_extraction_none(self):
        """Test timestamp extraction when no timestamp exists"""
        text = "ERROR Something went wrong without timestamp"
        timestamp = self.analyzer._extract_timestamp_from_text(text)
        
        assert timestamp is None
    
    def test_error_message_normalization(self):
        """Test error message normalization"""
        error_msg = "Connection failed to 192.168.1.100:5432 at 2024-01-15T14:30:25Z with ID 12345"
        normalized = self.analyzer._normalize_error_message(error_msg)
        
        assert "[IP_ADDRESS]" in normalized
        assert "[TIMESTAMP]" in normalized
        assert "[NUMBER]" in normalized
        assert "192.168.1.100" not in normalized
        assert "12345" not in normalized
    
    def test_error_message_normalization_uuid(self):
        """Test normalizing UUIDs in error messages"""
        error_msg = "Failed to process request 550e8400-e29b-41d4-a716-446655440000"
        normalized = self.analyzer._normalize_error_message(error_msg)
        
        assert "[UUID]" in normalized
        assert "550e8400-e29b-41d4-a716-446655440000" not in normalized
    
    def test_error_message_normalization_consistency(self):
        """Test that similar error messages normalize to the same result"""
        error1 = "Connection failed to 192.168.1.100 at 14:30:25 with ID 12345"
        error2 = "Connection failed to 10.0.0.1 at 15:45:30 with ID 67890"
        
        normalized1 = self.analyzer._normalize_error_message(error1)
        normalized2 = self.analyzer._normalize_error_message(error2)
        
        assert normalized1 == normalized2
    
    def test_log_level_extraction(self):
        """Test extracting log levels from text"""
        assert self.analyzer._extract_log_level("ERROR Something went wrong") == "ERROR"
        assert self.analyzer._extract_log_level("2024-01-15 INFO Application started") == "INFO"
        assert self.analyzer._extract_log_level("DEBUG: Processing request") == "DEBUG"
        assert self.analyzer._extract_log_level("warning: deprecated function") == "WARNING"
        assert self.analyzer._extract_log_level("No level here") is None
    
    def test_error_type_identification(self):
        """Test identifying different error types"""
        assert self.analyzer._identify_error_type("Exception occurred") == "exception"
        assert self.analyzer._identify_error_type("HTTP Status 404") == "http_error"
        assert self.analyzer._identify_error_type("Database connection failed") == "database_error"
        assert self.analyzer._identify_error_type("Connection timeout") == "timeout_error"
        assert self.analyzer._identify_error_type("OutOfMemoryError") == "memory_error"
        assert self.analyzer._identify_error_type("Normal log message") is None
    
    def test_public_normalize_error_message(self):
        """Test public interface for error message normalization"""
        error_msg = "Connection failed to 192.168.1.100:5432 at 2024-01-15T14:30:25Z with ID 12345"
        normalized = self.analyzer.normalize_error_message(error_msg)
        
        assert "[IP_ADDRESS]" in normalized
        assert "[TIMESTAMP]" in normalized
        assert "[NUMBER]" in normalized
        assert "192.168.1.100" not in normalized
        assert "12345" not in normalized
    
    def test_public_classify_error_type(self):
        """Test public interface for error type classification"""
        assert self.analyzer.classify_error_type("Exception occurred") == "exception"
        assert self.analyzer.classify_error_type("HTTP Status 404") == "http_error"
        assert self.analyzer.classify_error_type("Database connection failed") == "database_error"
        assert self.analyzer.classify_error_type("Connection timeout") == "timeout_error"
        assert self.analyzer.classify_error_type("OutOfMemoryError") == "memory_error"
        assert self.analyzer.classify_error_type("Normal log message") is None
    
    def test_parse_malformed_json(self):
        """Test parsing malformed JSON falls back to plain text"""
        malformed_json = '''{"timestamp": "2024-01-15T14:30:25Z", "level": "ERROR"
This is not valid JSON'''
        
        result = self.analyzer.parse_logs(malformed_json, "json")
        
        assert len(result.entries) == 2
        # First line should parse as JSON
        assert result.entries[0].level == "ERROR"
        # Second line should be treated as plain text
        assert result.entries[1].level is None
        assert result.entries[1].message == "This is not valid JSON"
    
    def test_complex_log_analysis(self):
        """Test complete log analysis workflow"""
        complex_log = '''2024-01-15T14:30:25.123Z ERROR Exception in application
Traceback (most recent call last):
  File "/app/services/user_service.py", line 156, in get_user
    user = database.fetch_user(user_id)
  File "/app/database/connection.py", line 89, in fetch_user
    return self.execute_query(query)
ValueError: User ID 12345 not found
2024-01-15T14:30:26.456Z INFO Retrying operation'''
        
        parsed_log = self.analyzer.parse_logs(complex_log, "plain")
        patterns = self.analyzer.extract_error_patterns(parsed_log)
        
        # Should have one main error pattern (duplicates filtered out)
        assert len(patterns) >= 1
        
        # Find the main error pattern (the one with the most information)
        main_pattern = max(patterns, key=lambda p: len(p.file_paths) + len(p.function_names))
        
        # Check error pattern extraction
        assert main_pattern.error_type == "exception"
        
        # Check stack trace extraction
        assert len(main_pattern.file_paths) >= 2
        assert "/app/services/user_service.py" in main_pattern.file_paths
        assert "/app/database/connection.py" in main_pattern.file_paths
        
        assert len(main_pattern.function_names) >= 2
        assert "get_user" in main_pattern.function_names
        assert "fetch_user" in main_pattern.function_names
        
        assert len(main_pattern.line_numbers) >= 2
        assert 156 in main_pattern.line_numbers
        assert 89 in main_pattern.line_numbers


class TestErrorPatternDataClass:
    """Test ErrorPattern data class"""
    
    def test_error_pattern_creation(self):
        """Test creating ErrorPattern instance"""
        pattern = ErrorPattern(
            error_type="exception",
            message="Test error",
            file_paths=["/app/test.py"],
            function_names=["test_func"],
            line_numbers=[42],
            timestamps=[datetime.now()],
            raw_stack_trace="Test stack trace"
        )
        
        assert pattern.error_type == "exception"
        assert pattern.message == "Test error"
        assert len(pattern.file_paths) == 1
        assert len(pattern.function_names) == 1
        assert len(pattern.line_numbers) == 1
        assert len(pattern.timestamps) == 1


class TestLogEntryDataClass:
    """Test LogEntry data class"""
    
    def test_log_entry_creation(self):
        """Test creating LogEntry instance"""
        timestamp = datetime.now()
        entry = LogEntry(
            timestamp=timestamp,
            level="ERROR",
            message="Test message",
            raw_content="Raw log line",
            metadata={"key": "value"}
        )
        
        assert entry.timestamp == timestamp
        assert entry.level == "ERROR"
        assert entry.message == "Test message"
        assert entry.raw_content == "Raw log line"
        assert entry.metadata["key"] == "value"


class TestStackTraceDataClass:
    """Test StackTrace data class"""
    
    def test_stack_trace_creation(self):
        """Test creating StackTrace instance"""
        stack_trace = StackTrace(
            file_paths=["/app/test.py"],
            function_names=["test_func"],
            line_numbers=[42],
            raw_trace="Raw stack trace"
        )
        
        assert len(stack_trace.file_paths) == 1
        assert len(stack_trace.function_names) == 1
        assert len(stack_trace.line_numbers) == 1
        assert stack_trace.raw_trace == "Raw stack trace"


if __name__ == "__main__":
    pytest.main([__file__])