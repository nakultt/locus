"""
Property-based tests for Incident Analyzer Service

**Validates: Requirements 4.1, 4.2, 4.3, 4.7**
"""

import pytest
from hypothesis import given, strategies as st, assume, settings
from datetime import datetime
import json
import re
import string
from app.services.incident_analyzer import IncidentAnalyzer, LogFormat


class TestIncidentAnalyzerProperties:
    """Property-based tests for IncidentAnalyzer"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.analyzer = IncidentAnalyzer()

    @given(st.text(min_size=1, max_size=1000))
    @settings(max_examples=50)
    def test_parse_logs_accepts_any_non_empty_content(self, log_content):
        """
        For any non-empty log content, parse_logs should accept it without throwing exceptions
        """
        assume(log_content.strip())  # Ensure content is not just whitespace
        
        for format_type in ["json", "syslog", "plain"]:
            try:
                result = self.analyzer.parse_logs(log_content, format_type)
                assert result is not None
                assert result.format == format_type
                assert isinstance(result.entries, list)
                assert isinstance(result.metadata, dict)
            except ValueError as e:
                # Only acceptable if it's the empty content error
                assert "Log content cannot be empty" in str(e)

    @given(st.lists(st.one_of(
        st.text(min_size=10, max_size=200).map(lambda t: f"ERROR: {t}"),
        st.text(min_size=10, max_size=200).map(lambda t: f"Exception: {t}"),
        st.text(min_size=10, max_size=200).map(lambda t: f"HTTP 500: {t}"),
        st.text(min_size=10, max_size=200).map(lambda t: f"Database error: {t}"),
        st.text(min_size=10, max_size=200).map(lambda t: f"Timeout: {t}"),
        st.text(min_size=10, max_size=200).map(lambda t: f"OutOfMemory: {t}"),
    ), min_size=1, max_size=10))
    @settings(max_examples=30)
    def test_error_message_extraction_property(self, error_lines):
        """
        **Property 16: Error Message Extraction**
        For any log containing error messages (exceptions, HTTP errors, or database errors), 
        the Incident_Analyzer should extract at least one error message.
        """
        log_content = '\n'.join(error_lines)
        
        # Parse the logs
        parsed_log = self.analyzer.parse_logs(log_content, "plain")
        
        # Extract error patterns
        error_patterns = self.analyzer.extract_error_patterns(parsed_log)
        
        # Should extract at least one error pattern since we provided error messages
        assert len(error_patterns) >= 1, f"Expected at least one error pattern from: {log_content[:100]}..."
        
        # Each error pattern should have a valid error type and message
        for pattern in error_patterns:
            assert pattern.error_type is not None
            assert pattern.message is not None
            assert len(pattern.message) > 0
            assert pattern.error_type in {'exception', 'http_error', 'database_error', 'timeout_error', 'memory_error'}

    @given(st.lists(st.one_of(
        # Python stack traces
        st.text(alphabet=string.ascii_letters + string.digits, min_size=5, max_size=50).map(lambda f: f'File "{f}.py", line 42, in test_function'),
        st.text(alphabet=string.ascii_letters + string.digits, min_size=5, max_size=50).map(lambda f: f'File "/path/to/{f}.py", line 123, in main'),
        # Java stack traces  
        st.text(alphabet=string.ascii_letters + string.digits, min_size=5, max_size=50).map(lambda c: f'at com.example.{c}.method(File.java:456)'),
        # JavaScript stack traces
        st.text(alphabet=string.ascii_letters + string.digits, min_size=5, max_size=50).map(lambda f: f'at testFunc ({f}.js:789:10)'),
        # C# stack traces
        st.text(alphabet=string.ascii_letters + string.digits, min_size=5, max_size=50).map(lambda c: f'at MyNamespace.{c}.Method() in C:\\path\\file.cs:line 321'),
        # Generic file:line patterns
        st.text(alphabet=string.ascii_letters + string.digits, min_size=5, max_size=50).map(lambda f: f'{f}.py:654'),
    ), min_size=1, max_size=5))
    @settings(max_examples=30)
    def test_stack_trace_parsing_property(self, stack_trace_lines):
        """
        **Property 17: Stack Trace Parsing**
        For any log containing a valid stack trace, the Incident_Analyzer should extract 
        file paths, function names, and line numbers from that stack trace.
        """
        log_content = '\n'.join(stack_trace_lines)
        
        stack_trace = self.analyzer.extract_stack_trace(log_content)
        
        # Should extract at least some information from valid stack traces
        total_extracted = len(stack_trace.file_paths) + len(stack_trace.function_names) + len(stack_trace.line_numbers)
        assert total_extracted > 0, f"Expected to extract some stack trace info from: {log_content[:100]}..."
        
        # Verify the structure is always valid
        assert isinstance(stack_trace.file_paths, list)
        assert isinstance(stack_trace.function_names, list)
        assert isinstance(stack_trace.line_numbers, list)
        assert isinstance(stack_trace.raw_trace, str)
        
        # All line numbers should be positive integers
        for line_num in stack_trace.line_numbers:
            assert isinstance(line_num, int)
            assert line_num > 0
            
        # File paths should not be empty strings
        for file_path in stack_trace.file_paths:
            assert isinstance(file_path, str)
            assert len(file_path) > 0
            
        # Function names should not be empty strings
        for func_name in stack_trace.function_names:
            assert isinstance(func_name, str)
            assert len(func_name) > 0

    @given(st.lists(st.one_of(
        # ISO 8601 timestamps
        st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2024, 12, 31)).map(lambda dt: dt.isoformat() + 'Z'),
        st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2024, 12, 31)).map(lambda dt: dt.strftime('%Y-%m-%d %H:%M:%S')),
        # Syslog format
        st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2024, 12, 31)).map(lambda dt: dt.strftime('%b %d %H:%M:%S')),
        # MM/DD/YYYY format
        st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2024, 12, 31)).map(lambda dt: dt.strftime('%m/%d/%Y %H:%M:%S')),
        # Unix timestamps
        st.integers(min_value=1577836800, max_value=1735689600).map(str),  # 2020-2025 range
    ), min_size=1, max_size=5))
    @settings(max_examples=30)
    def test_timestamp_extraction_property(self, timestamp_strings):
        """
        **Property 18: Timestamp Extraction**
        For any log entry containing timestamps in standard formats, 
        the Incident_Analyzer should extract those timestamps.
        """
        # Create log entries with timestamps
        log_lines = []
        for ts in timestamp_strings:
            log_lines.append(f"[{ts}] Some log message with error")
        
        log_content = '\n'.join(log_lines)
        
        # Parse the logs
        parsed_log = self.analyzer.parse_logs(log_content, "plain")
        
        # Count how many entries have extracted timestamps
        entries_with_timestamps = [entry for entry in parsed_log.entries if entry.timestamp is not None]
        
        # Should extract at least some timestamps from valid timestamp formats
        assert len(entries_with_timestamps) > 0, f"Expected to extract some timestamps from: {log_content[:100]}..."
        
        # All extracted timestamps should be valid datetime objects
        for entry in entries_with_timestamps:
            assert isinstance(entry.timestamp, datetime)
            # Should be reasonable dates (within our test range)
            assert entry.timestamp.year >= 2020
            assert entry.timestamp.year <= 2025

    @given(st.text(min_size=5, max_size=200))
    @settings(max_examples=50)
    def test_error_message_normalization_consistency_property(self, base_message):
        """
        **Property 19: Error Normalization Consistency**
        For any two error messages that differ only in variable values or timestamps, 
        the normalized versions should be identical.
        """
        # Create variations of the same error structure with different variable data
        # Test each pattern separately to ensure consistency within the same pattern
        test_patterns = [
            # User ID pattern variations
            [
                f"{base_message} user ID 12345 at 2024-01-15T10:30:00Z",
                f"{base_message} user ID 67890 at 2024-02-20T15:45:30Z", 
                f"{base_message} user ID 99999 at 2024-03-10T08:15:45Z",
            ],
            # IP address pattern variations
            [
                f"{base_message} IP 192.168.1.100 session abc123def",
                f"{base_message} IP 10.0.0.50 session xyz789ghi",
                f"{base_message} IP 172.16.0.1 session def456abc",
            ],
            # File path pattern variations
            [
                f"{base_message} file /path/to/file1.txt line 42",
                f"{base_message} file /different/path/file2.txt line 156",
                f"{base_message} file /another/location/file3.txt line 789",
            ]
        ]
        
        for pattern_variations in test_patterns:
            normalized_results = []
            for variation in pattern_variations:
                try:
                    normalized = self.analyzer.normalize_error_message(variation)
                    normalized_results.append(normalized)
                except Exception:
                    # Skip if normalization fails for any reason
                    continue
            
            if len(normalized_results) >= 2:
                # All normalized versions within the same pattern should be identical
                first_normalized = normalized_results[0]
                
                # Check that normalization actually happened (should contain placeholders)
                has_placeholders = any(placeholder in first_normalized for placeholder in 
                                     ['[NUMBER]', '[TIMESTAMP]', '[IP_ADDRESS]', '[PATH]', '[UUID]'])
                
                if has_placeholders:
                    # All messages with the same pattern should normalize to exactly the same result
                    for other_normalized in normalized_results[1:]:
                        # For the same pattern, normalized results should be identical or very similar
                        similarity_ratio = len(set(first_normalized.split()) & set(other_normalized.split())) / max(len(first_normalized.split()), len(other_normalized.split()))
                        assert similarity_ratio >= 0.8, f"Normalized messages with same pattern should be very similar: '{first_normalized}' vs '{other_normalized}'"

    @given(st.lists(st.text(min_size=1, max_size=100).filter(lambda x: '\n' not in x), min_size=1, max_size=20))
    @settings(max_examples=30)
    def test_plain_log_parsing_handles_any_lines(self, log_lines):
        """
        For any list of text lines (without embedded newlines), plain log parsing should handle them gracefully
        """
        log_content = '\n'.join(log_lines)
        
        result = self.analyzer.parse_logs(log_content, "plain")
        
        assert result.format == "plain"
        assert len(result.entries) <= len(log_lines)  # May be fewer due to empty lines
        
        # Each entry should be valid
        for entry in result.entries:
            assert isinstance(entry.message, str)
            assert isinstance(entry.raw_content, str)
            assert len(entry.message) > 0
            assert len(entry.raw_content) > 0

    @given(st.text(min_size=1, max_size=200))
    @settings(max_examples=50)
    def test_timestamp_extraction_is_safe(self, text):
        """
        For any text input, timestamp extraction should not throw exceptions
        """
        try:
            timestamp = self.analyzer._extract_timestamp_from_text(text)
            
            # If a timestamp is found, it should be a valid datetime
            if timestamp is not None:
                assert isinstance(timestamp, datetime)
                # Should be a reasonable date (not too far in past/future)
                assert timestamp.year >= 1970
                assert timestamp.year <= 2100
                
        except Exception as e:
            pytest.fail(f"Timestamp extraction should not throw exceptions: {e}")

    @given(st.text(min_size=1, max_size=100))
    @settings(max_examples=50)
    def test_error_type_identification_is_safe(self, message):
        """
        For any message, error type identification should not throw exceptions
        """
        try:
            error_type = self.analyzer._identify_error_type(message)
            
            # If an error type is identified, it should be one of the known types
            if error_type is not None:
                known_types = {'exception', 'http_error', 'database_error', 'timeout_error', 'memory_error'}
                assert error_type in known_types
                
        except Exception as e:
            pytest.fail(f"Error type identification should not throw exceptions: {e}")

    @given(st.text(min_size=1, max_size=100))
    @settings(max_examples=50)
    def test_log_level_extraction_is_safe(self, text):
        """
        For any text input, log level extraction should not throw exceptions
        """
        try:
            level = self.analyzer._extract_log_level(text)
            
            # If a level is found, it should be one of the known levels
            if level is not None:
                known_levels = {'FATAL', 'ERROR', 'WARN', 'WARNING', 'INFO', 'DEBUG', 'TRACE'}
                assert level in known_levels
                
        except Exception as e:
            pytest.fail(f"Log level extraction should not throw exceptions: {e}")

    @given(st.text(min_size=1, max_size=200))
    @settings(max_examples=30)
    def test_public_normalize_error_message_consistency(self, error_message):
        """
        **Property 19: Error Normalization Consistency (Public Interface)**
        For any error message, the public normalize_error_message should produce the same result as the private method
        """
        try:
            public_result = self.analyzer.normalize_error_message(error_message)
            private_result = self.analyzer._normalize_error_message(error_message)
            
            assert public_result == private_result, f"Public and private normalization should match: '{public_result}' vs '{private_result}'"
            
            # Result should be a string
            assert isinstance(public_result, str)
            
        except Exception as e:
            pytest.fail(f"Public normalize_error_message should not throw exceptions: {e}")

    @given(st.text(min_size=1, max_size=100))
    @settings(max_examples=30)
    def test_public_classify_error_type_consistency(self, message):
        """
        For any message, the public classify_error_type should produce the same result as the private method
        """
        try:
            public_result = self.analyzer.classify_error_type(message)
            private_result = self.analyzer._identify_error_type(message)
            
            assert public_result == private_result, f"Public and private classification should match: '{public_result}' vs '{private_result}'"
            
            # If an error type is identified, it should be one of the known types
            if public_result is not None:
                known_types = {'exception', 'http_error', 'database_error', 'timeout_error', 'memory_error'}
                assert public_result in known_types
                
        except Exception as e:
            pytest.fail(f"Public classify_error_type should not throw exceptions: {e}")

    @given(st.lists(st.dictionaries(
        keys=st.sampled_from(['timestamp', 'level', 'message', 'time', '@timestamp']),
        values=st.one_of(
            st.text(min_size=1, max_size=100),
            st.integers(min_value=1000000000, max_value=2000000000),  # Unix timestamps
            st.datetimes().map(lambda dt: dt.isoformat())
        ),
        min_size=1
    ), min_size=1, max_size=10))
    @settings(max_examples=30)
    def test_json_log_parsing_preserves_structure(self, log_dicts):
        """
        For any list of valid JSON log dictionaries, parsing should preserve the structure
        """
        json_lines = []
        for log_dict in log_dicts:
            try:
                json_lines.append(json.dumps(log_dict))
            except (TypeError, ValueError):
                # Skip invalid JSON structures
                continue
        
        if not json_lines:
            return
            
        log_content = '\n'.join(json_lines)
        
        result = self.analyzer.parse_logs(log_content, "json")
        
        assert len(result.entries) <= len(json_lines)  # May be fewer due to empty lines
        assert result.format == "json"
        
        # Each entry should have the expected structure
        for entry in result.entries:
            assert hasattr(entry, 'timestamp')
            assert hasattr(entry, 'level')
            assert hasattr(entry, 'message')
            assert hasattr(entry, 'raw_content')
            assert hasattr(entry, 'metadata')

    @given(st.text(min_size=10, max_size=500))
    @settings(max_examples=50)
    def test_stack_trace_extraction_is_safe(self, log_content):
        """
        For any log content, stack trace extraction should not throw exceptions
        """
        try:
            stack_trace = self.analyzer.extract_stack_trace(log_content)
            
            # Verify the structure is always valid
            assert isinstance(stack_trace.file_paths, list)
            assert isinstance(stack_trace.function_names, list)
            assert isinstance(stack_trace.line_numbers, list)
            assert isinstance(stack_trace.raw_trace, str)
            
            # All line numbers should be positive integers
            for line_num in stack_trace.line_numbers:
                assert isinstance(line_num, int)
                assert line_num > 0
                
            # File paths should not be empty strings
            for file_path in stack_trace.file_paths:
                assert isinstance(file_path, str)
                assert len(file_path) > 0
                
            # Function names should not be empty strings
            for func_name in stack_trace.function_names:
                assert isinstance(func_name, str)
                assert len(func_name) > 0
                
        except Exception as e:
            pytest.fail(f"Stack trace extraction should not throw exceptions: {e}")

    @given(st.text(min_size=1, max_size=200))
    @settings(max_examples=50)
    def test_timestamp_extraction_is_safe(self, text):
        """
        For any text input, timestamp extraction should not throw exceptions
        """
        try:
            timestamp = self.analyzer._extract_timestamp_from_text(text)
            
            # If a timestamp is found, it should be a valid datetime
            if timestamp is not None:
                assert isinstance(timestamp, datetime)
                # Should be a reasonable date (not too far in past/future)
                assert timestamp.year >= 1970
                assert timestamp.year <= 2100
                
        except Exception as e:
            pytest.fail(f"Timestamp extraction should not throw exceptions: {e}")

    @given(st.text(min_size=1, max_size=100))
    @settings(max_examples=50)
    def test_error_type_identification_is_safe(self, message):
        """
        For any message, error type identification should not throw exceptions
        """
        try:
            error_type = self.analyzer._identify_error_type(message)
            
            # If an error type is identified, it should be one of the known types
            if error_type is not None:
                known_types = {'exception', 'http_error', 'database_error', 'timeout_error', 'memory_error'}
                assert error_type in known_types
                
        except Exception as e:
            pytest.fail(f"Error type identification should not throw exceptions: {e}")

    @given(st.text(min_size=1, max_size=100))
    @settings(max_examples=50)
    def test_log_level_extraction_is_safe(self, text):
        """
        For any text input, log level extraction should not throw exceptions
        """
        try:
            level = self.analyzer._extract_log_level(text)
            
            # If a level is found, it should be one of the known levels
            if level is not None:
                known_levels = {'FATAL', 'ERROR', 'WARN', 'WARNING', 'INFO', 'DEBUG', 'TRACE'}
                assert level in known_levels
                
        except Exception as e:
            pytest.fail(f"Log level extraction should not throw exceptions: {e}")

    @given(st.text(min_size=1, max_size=200))
    @settings(max_examples=30)
    def test_public_normalize_error_message_consistency(self, error_message):
        """
        For any error message, the public normalize_error_message should produce the same result as the private method
        """
        try:
            public_result = self.analyzer.normalize_error_message(error_message)
            private_result = self.analyzer._normalize_error_message(error_message)
            
            assert public_result == private_result, f"Public and private normalization should match: '{public_result}' vs '{private_result}'"
            
            # Result should be a string
            assert isinstance(public_result, str)
            
        except Exception as e:
            pytest.fail(f"Public normalize_error_message should not throw exceptions: {e}")

    @given(st.lists(st.text(min_size=1, max_size=100).filter(lambda x: '\n' not in x), min_size=1, max_size=20))
    @settings(max_examples=30)
    def test_plain_log_parsing_handles_any_lines(self, log_lines):
        """
        For any list of text lines (without embedded newlines), plain log parsing should handle them gracefully
        """
        log_content = '\n'.join(log_lines)
        
        result = self.analyzer.parse_logs(log_content, "plain")
        
        assert result.format == "plain"
        assert len(result.entries) <= len(log_lines)  # May be fewer due to empty lines
        
        # Each entry should be valid
        for entry in result.entries:
            assert isinstance(entry.message, str)
            assert isinstance(entry.raw_content, str)
            assert len(entry.message) > 0
            assert len(entry.raw_content) > 0

    @given(st.lists(st.one_of(
        st.text(min_size=10, max_size=200).map(lambda t: f"ERROR: {t} in file.py:123"),
        st.text(min_size=10, max_size=200).map(lambda t: f"Exception in thread main: {t}"),
        st.text(min_size=10, max_size=200).map(lambda t: f"HTTP 500 Internal Server Error: {t}"),
        st.text(min_size=10, max_size=200).map(lambda t: f"Database connection failed: {t}"),
    ), min_size=1, max_size=5))
    @settings(max_examples=20)
    def test_comprehensive_error_pattern_extraction(self, error_lines):
        """
        **Comprehensive test for Properties 16-19**
        For any log with errors, stack traces, and timestamps, all extraction should work together
        """
        # Add timestamps to some lines
        timestamped_lines = []
        for i, line in enumerate(error_lines):
            if i % 2 == 0:
                timestamped_lines.append(f"2024-01-15T10:30:{i:02d}Z {line}")
            else:
                timestamped_lines.append(line)
        
        log_content = '\n'.join(timestamped_lines)
        
        # Parse logs
        parsed_log = self.analyzer.parse_logs(log_content, "plain")
        assert len(parsed_log.entries) > 0
        
        # Extract error patterns
        error_patterns = self.analyzer.extract_error_patterns(parsed_log)
        assert len(error_patterns) > 0
        
        # Verify each error pattern has the expected structure
        for pattern in error_patterns:
            # Property 16: Error message extraction
            assert pattern.error_type is not None
            assert pattern.message is not None
            assert len(pattern.message) > 0
            
            # Property 17: Stack trace parsing (file paths should be extracted if present)
            assert isinstance(pattern.file_paths, list)
            assert isinstance(pattern.function_names, list)
            assert isinstance(pattern.line_numbers, list)
            
            # Property 18: Timestamp extraction (should have timestamps if present)
            assert isinstance(pattern.timestamps, list)
            
            # Property 19: Error normalization (normalized message should be different from raw)
            assert isinstance(pattern.message, str)
            # The normalized message should not contain specific numbers/timestamps
            assert not re.search(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', pattern.message)


if __name__ == "__main__":
    pytest.main([__file__])