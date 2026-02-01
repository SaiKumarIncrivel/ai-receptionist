"""Tests for LLM slot extraction."""

import pytest
from unittest.mock import AsyncMock
from dataclasses import dataclass
from datetime import date, time

from app.core.intelligence.slots.types import ExtractedSlots, AppointmentType
from app.core.intelligence.slots.extractor import SlotExtractor


@dataclass
class MockClaudeResponse:
    """Mock Claude response."""
    content: str
    model: str = "claude-3-5-haiku-20241022"
    input_tokens: int = 100
    output_tokens: int = 50
    stop_reason: str = "end_turn"
    latency_ms: float = 50.0


class TestSlotExtractor:
    """Test LLM-based slot extraction."""

    @pytest.fixture
    def mock_claude_client(self):
        """Create mock Claude client."""
        return AsyncMock()

    @pytest.fixture
    def extractor(self, mock_claude_client):
        """Create extractor with mock client."""
        return SlotExtractor(claude_client=mock_claude_client)

    def _mock_response(self, mock_client, json_response: str):
        """Helper to mock Claude response."""
        mock_client.generate.return_value = MockClaudeResponse(content=json_response)

    @pytest.mark.asyncio
    async def test_extract_provider(self, extractor, mock_claude_client):
        """Test provider extraction."""
        self._mock_response(
            mock_claude_client,
            '''
            {
                "provider_name": "Smith",
                "date": null,
                "time": null,
                "date_raw": null,
                "time_raw": null,
                "is_flexible": false,
                "appointment_type": null,
                "reason": null,
                "patient_name": null,
                "patient_phone": null
            }
            ''',
        )

        result = await extractor.extract("I want to see Dr. Smith")

        assert result.provider_name == "Smith"

    @pytest.mark.asyncio
    async def test_extract_date_time(self, extractor, mock_claude_client):
        """Test date and time extraction."""
        self._mock_response(
            mock_claude_client,
            '''
            {
                "provider_name": null,
                "date": "2024-01-15",
                "time": "14:00",
                "date_raw": "next Tuesday",
                "time_raw": "2pm",
                "is_flexible": false,
                "appointment_type": null,
                "reason": null,
                "patient_name": null,
                "patient_phone": null
            }
            ''',
        )

        result = await extractor.extract("Next Tuesday at 2pm works")

        assert result.date == date(2024, 1, 15)
        assert result.time == time(14, 0)
        assert result.date_raw == "next Tuesday"
        assert result.time_raw == "2pm"

    @pytest.mark.asyncio
    async def test_extract_flexible_time(self, extractor, mock_claude_client):
        """Test flexible time detection."""
        self._mock_response(
            mock_claude_client,
            '''
            {
                "provider_name": null,
                "date": null,
                "time": null,
                "date_raw": null,
                "time_raw": "around 3pm",
                "is_flexible": true,
                "appointment_type": null,
                "reason": null,
                "patient_name": null,
                "patient_phone": null
            }
            ''',
        )

        result = await extractor.extract("Around 3pm would be great")

        assert result.time_raw == "around 3pm"
        assert result.is_flexible is True

    @pytest.mark.asyncio
    async def test_extract_all_slots(self, extractor, mock_claude_client):
        """Test extracting multiple slots at once."""
        self._mock_response(
            mock_claude_client,
            '''
            {
                "provider_name": "Johnson",
                "date": "2024-01-15",
                "time": "09:00",
                "date_raw": "January 15",
                "time_raw": "morning",
                "is_flexible": true,
                "appointment_type": "checkup",
                "reason": "annual physical",
                "patient_name": null,
                "patient_phone": null
            }
            ''',
        )

        result = await extractor.extract(
            "I need a checkup with Dr. Johnson on January 15, morning works"
        )

        assert result.provider_name == "Johnson"
        assert result.date == date(2024, 1, 15)
        assert result.time == time(9, 0)
        assert result.appointment_type == AppointmentType.CHECKUP
        assert result.reason == "annual physical"
        assert result.is_flexible is True

    @pytest.mark.asyncio
    async def test_extract_patient_info(self, extractor, mock_claude_client):
        """Test patient information extraction."""
        self._mock_response(
            mock_claude_client,
            '''
            {
                "provider_name": null,
                "date": null,
                "time": null,
                "date_raw": null,
                "time_raw": null,
                "is_flexible": false,
                "appointment_type": null,
                "reason": null,
                "patient_name": "John Smith",
                "patient_phone": "555-123-4567"
            }
            ''',
        )

        result = await extractor.extract("My name is John Smith, phone is 555-123-4567")

        assert result.patient_name == "John Smith"
        assert result.patient_phone == "555-123-4567"
        assert result.has_patient_info is True

    @pytest.mark.asyncio
    async def test_extract_empty_message(self, extractor):
        """Test empty message returns empty slots."""
        result = await extractor.extract("")

        assert result.has_any() is False

    @pytest.mark.asyncio
    async def test_extract_with_markdown_response(self, extractor, mock_claude_client):
        """Test extraction handles markdown-wrapped JSON."""
        self._mock_response(
            mock_claude_client,
            '''```json
            {
                "provider_name": "Smith",
                "date": null,
                "time": null,
                "date_raw": null,
                "time_raw": null,
                "is_flexible": false,
                "appointment_type": null,
                "reason": null,
                "patient_name": null,
                "patient_phone": null
            }
            ```''',
        )

        result = await extractor.extract("I want to see Dr. Smith")

        assert result.provider_name == "Smith"


class TestExtractedSlots:
    """Test ExtractedSlots model."""

    def test_has_any_true(self):
        """Test has_any returns True when slots present."""
        slots = ExtractedSlots(provider_name="Smith")
        assert slots.has_any() is True

    def test_has_any_false(self):
        """Test has_any returns False when empty."""
        slots = ExtractedSlots()
        assert slots.has_any() is False

    def test_has_datetime(self):
        """Test has_datetime property."""
        with_date = ExtractedSlots(date=date(2024, 1, 15))
        with_time = ExtractedSlots(time=time(14, 0))
        with_raw = ExtractedSlots(date_raw="tomorrow")
        empty = ExtractedSlots()

        assert with_date.has_datetime is True
        assert with_time.has_datetime is True
        assert with_raw.has_datetime is True
        assert empty.has_datetime is False

    def test_merge(self):
        """Test merging of extracted slots."""
        slots1 = ExtractedSlots(
            provider_name="Smith",
            date=date(2024, 1, 15),
        )

        slots2 = ExtractedSlots(
            time=time(14, 30),
            reason="checkup",
        )

        merged = slots1.merge(slots2)

        assert merged.provider_name == "Smith"
        assert merged.date == date(2024, 1, 15)
        assert merged.time == time(14, 30)
        assert merged.reason == "checkup"

    def test_merge_prefers_other(self):
        """Test merge prefers non-None values from other."""
        slots1 = ExtractedSlots(provider_name="Smith")
        slots2 = ExtractedSlots(provider_name="Johnson")

        merged = slots1.merge(slots2)

        assert merged.provider_name == "Johnson"

    def test_to_dict(self):
        """Test conversion to dictionary."""
        slots = ExtractedSlots(
            provider_name="Smith",
            date=date(2024, 1, 15),
            time=time(14, 0),
            reason="checkup",
        )

        d = slots.to_dict()

        assert d["provider_name"] == "Smith"
        assert d["date"] == "2024-01-15"
        assert d["time"] == "14:00:00"
        assert d["reason"] == "checkup"
        assert "is_flexible" not in d  # False values excluded
