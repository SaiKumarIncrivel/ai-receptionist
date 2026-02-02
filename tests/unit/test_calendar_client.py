"""Tests for Calendar Agent HTTP client."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import Response

from app.core.scheduling.calendar_client import (
    CalendarAgentClient,
    TimeSlot,
    BookingResult,
    Provider,
)


class TestTimeSlot:
    """Test TimeSlot dataclass."""

    def test_from_dict(self):
        """Test creating from dict."""
        data = {
            "slot_id": "slot-123",
            "provider_id": "doc-456",
            "provider_name": "Dr. Smith",
            "start_time": "2024-01-15T10:00:00",
            "end_time": "2024-01-15T10:30:00",
            "duration_minutes": 30,
        }

        slot = TimeSlot.from_dict(data)

        assert slot.slot_id == "slot-123"
        assert slot.provider_id == "doc-456"
        assert slot.provider_name == "Dr. Smith"
        assert slot.duration_minutes == 30

    def test_from_dict_with_alternate_keys(self):
        """Test with alternate key names."""
        data = {
            "id": "slot-123",
            "provider_id": "doc-456",
            "provider_name": "Dr. Smith",
            "start": "2024-01-15T10:00:00",
            "end": "2024-01-15T10:30:00",
        }

        slot = TimeSlot.from_dict(data)

        assert slot.slot_id == "slot-123"
        assert slot.start_time == "2024-01-15T10:00:00"

    def test_to_dict(self):
        """Test conversion to dict."""
        slot = TimeSlot(
            slot_id="slot-123",
            provider_id="doc-456",
            provider_name="Dr. Smith",
            start_time="2024-01-15T10:00:00",
            end_time="2024-01-15T10:30:00",
        )

        d = slot.to_dict()

        assert d["slot_id"] == "slot-123"
        assert d["provider_name"] == "Dr. Smith"


class TestProvider:
    """Test Provider dataclass."""

    def test_from_dict(self):
        """Test creating from dict."""
        data = {
            "id": "doc-123",
            "name": "Dr. Jane Smith",
            "specialty": "General Practice",
        }

        provider = Provider.from_dict(data)

        assert provider.id == "doc-123"
        assert provider.name == "Dr. Jane Smith"
        assert provider.specialty == "General Practice"


class TestCalendarAgentClient:
    """Test CalendarAgentClient."""

    @pytest.fixture
    def client(self):
        """Create client with mock HTTP."""
        return CalendarAgentClient(base_url="http://test:8001")

    @pytest.fixture
    def mock_httpx_client(self):
        """Create mock httpx client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_list_providers(self, client, mock_httpx_client):
        """Test listing providers."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "providers": [
                {"id": "doc-1", "name": "Dr. Smith", "specialty": "General"},
                {"id": "doc-2", "name": "Dr. Jones", "specialty": "Cardiology"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client.get = AsyncMock(return_value=mock_response)
        client._client = mock_httpx_client

        providers = await client.list_providers("clinic-123")

        assert len(providers) == 2
        assert providers[0].name == "Dr. Smith"
        assert providers[1].specialty == "Cardiology"

    @pytest.mark.asyncio
    async def test_list_providers_handles_list_response(self, client, mock_httpx_client):
        """Test handling direct list response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": "doc-1", "name": "Dr. Smith"},
        ]
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client.get = AsyncMock(return_value=mock_response)
        client._client = mock_httpx_client

        providers = await client.list_providers("clinic-123")

        assert len(providers) == 1

    @pytest.mark.asyncio
    async def test_find_provider_by_name(self, client, mock_httpx_client):
        """Test finding provider by name."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "providers": [
                {"id": "doc-1", "name": "Dr. Smith"},
                {"id": "doc-2", "name": "Dr. Jones"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client.get = AsyncMock(return_value=mock_response)
        client._client = mock_httpx_client

        provider = await client.find_provider_by_name("clinic-123", "smith")

        assert provider is not None
        assert provider.name == "Dr. Smith"

    @pytest.mark.asyncio
    async def test_find_provider_not_found(self, client, mock_httpx_client):
        """Test provider not found."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"providers": []}
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client.get = AsyncMock(return_value=mock_response)
        client._client = mock_httpx_client

        provider = await client.find_provider_by_name("clinic-123", "unknown")

        assert provider is None

    @pytest.mark.asyncio
    async def test_find_available_slots(self, client, mock_httpx_client):
        """Test finding available slots."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "slots": [
                {
                    "slot_id": "slot-1",
                    "provider_id": "doc-1",
                    "provider_name": "Dr. Smith",
                    "start_time": "2024-01-15T09:00:00",
                    "end_time": "2024-01-15T09:30:00",
                },
                {
                    "slot_id": "slot-2",
                    "provider_id": "doc-1",
                    "provider_name": "Dr. Smith",
                    "start_time": "2024-01-15T10:00:00",
                    "end_time": "2024-01-15T10:30:00",
                },
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_httpx_client

        slots = await client.find_available_slots(
            tenant_id="clinic-123",
            provider_id="doc-1",
            date_from="2024-01-15",
        )

        assert len(slots) == 2
        assert slots[0].slot_id == "slot-1"

    @pytest.mark.asyncio
    async def test_create_booking_success(self, client, mock_httpx_client):
        """Test successful booking creation."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "booking_id": "booking-123",
            "message": "Appointment confirmed",
        }

        mock_httpx_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_httpx_client

        result = await client.create_booking(
            tenant_id="clinic-123",
            slot_id="slot-1",
            patient_name="John Doe",
            patient_phone="555-1234",
        )

        assert result.success is True
        assert result.booking_id == "booking-123"

    @pytest.mark.asyncio
    async def test_create_booking_failure(self, client, mock_httpx_client):
        """Test failed booking creation."""
        mock_response = MagicMock()
        mock_response.status_code = 409
        mock_response.json.return_value = {
            "error_code": "slot_taken",
            "message": "This slot is no longer available",
            "suggestions": ["Try a different time"],
        }

        mock_httpx_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_httpx_client

        result = await client.create_booking(
            tenant_id="clinic-123",
            slot_id="slot-1",
            patient_name="John Doe",
        )

        assert result.success is False
        assert result.error_code == "slot_taken"
        assert "different time" in result.suggestions[0]

    @pytest.mark.asyncio
    async def test_cancel_booking_success(self, client, mock_httpx_client):
        """Test successful cancellation."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_httpx_client.delete = AsyncMock(return_value=mock_response)
        client._client = mock_httpx_client

        result = await client.cancel_booking(
            tenant_id="clinic-123",
            booking_id="booking-123",
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_get_booking(self, client, mock_httpx_client):
        """Test getting booking details."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "booking_id": "booking-123",
            "patient_name": "John Doe",
            "provider_name": "Dr. Smith",
            "start_time": "2024-01-15T10:00:00",
        }

        mock_httpx_client.get = AsyncMock(return_value=mock_response)
        client._client = mock_httpx_client

        booking = await client.get_booking("clinic-123", "booking-123")

        assert booking is not None
        assert booking["patient_name"] == "John Doe"

    @pytest.mark.asyncio
    async def test_get_booking_not_found(self, client, mock_httpx_client):
        """Test booking not found."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_httpx_client.get = AsyncMock(return_value=mock_response)
        client._client = mock_httpx_client

        booking = await client.get_booking("clinic-123", "nonexistent")

        assert booking is None

    @pytest.mark.asyncio
    async def test_close_client(self, client, mock_httpx_client):
        """Test closing client."""
        mock_httpx_client.aclose = AsyncMock()
        client._client = mock_httpx_client

        await client.close()

        mock_httpx_client.aclose.assert_called_once()
        assert client._client is None
