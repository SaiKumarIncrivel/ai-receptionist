"""
HTTP client for Calendar Agent.

Calendar Agent runs separately and exposes REST API for:
- Listing providers
- Finding available slots
- Creating/cancelling bookings
"""

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class TimeSlot:
    """Available time slot from Calendar Agent."""

    slot_id: str
    provider_id: str
    provider_name: str
    start_time: str  # ISO format
    end_time: str
    duration_minutes: int = 30

    @classmethod
    def from_dict(cls, data: dict) -> "TimeSlot":
        """Create from API response dict."""
        return cls(
            slot_id=data.get("slot_id", data.get("id", "")),
            provider_id=data.get("provider_id", ""),
            provider_name=data.get("provider_name", ""),
            start_time=data.get("start_time", data.get("start", "")),
            end_time=data.get("end_time", data.get("end", "")),
            duration_minutes=data.get("duration_minutes", 30),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "slot_id": self.slot_id,
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_minutes": self.duration_minutes,
        }


@dataclass
class BookingResult:
    """Result of a booking attempt."""

    success: bool
    booking_id: Optional[str] = None
    message: Optional[str] = None
    error_code: Optional[str] = None

    # For AI-friendly responses
    suggestions: Optional[list[str]] = None
    alternative_slots: Optional[list[TimeSlot]] = None


@dataclass
class Provider:
    """Provider/doctor info."""

    id: str
    name: str
    specialty: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "Provider":
        """Create from API response dict."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            specialty=data.get("specialty"),
        )


class CalendarAgentClient:
    """
    HTTP client for Calendar Agent API.

    Calendar Agent exposes:
    - GET /api/providers - List providers
    - POST /api/slots/find - Find available slots
    - POST /api/bookings - Create booking
    - DELETE /api/bookings/{id} - Cancel booking
    - GET /api/bookings/{id} - Get booking status
    """

    def __init__(self, base_url: Optional[str] = None, timeout: float = 30.0):
        """Initialize client.

        Args:
            base_url: Calendar Agent base URL (defaults to settings)
            timeout: Request timeout in seconds
        """
        settings = get_settings()
        self.base_url = base_url or settings.calendar_agent_url
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # === Providers ===

    async def list_providers(self, tenant_id: str) -> list[Provider]:
        """List available providers/doctors.

        Args:
            tenant_id: Clinic/tenant identifier

        Returns:
            List of providers
        """
        client = await self._get_client()

        try:
            response = await client.get(
                "/api/providers",
                headers={"X-Tenant-ID": tenant_id},
            )
            response.raise_for_status()

            data = response.json()
            if isinstance(data, list):
                providers = data
            else:
                providers = data.get("providers", data.get("items", []))
            return [Provider.from_dict(p) for p in providers]

        except httpx.HTTPError as e:
            logger.error(f"Failed to list providers: {e}")
            return []

    async def find_provider_by_name(self, tenant_id: str, name: str) -> Optional[Provider]:
        """Find provider by name (partial match).

        Args:
            tenant_id: Clinic/tenant identifier
            name: Provider name to search for

        Returns:
            Provider if found, None otherwise
        """
        providers = await self.list_providers(tenant_id)

        name_lower = name.lower()
        for provider in providers:
            if name_lower in provider.name.lower():
                return provider

        return None

    # === Availability ===

    async def find_available_slots(
        self,
        tenant_id: str,
        provider_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        time_preference: Optional[str] = None,
        duration_minutes: int = 30,
        limit: int = 5,
    ) -> list[TimeSlot]:
        """Find available appointment slots.

        Args:
            tenant_id: Clinic/tenant identifier
            provider_id: Filter by provider
            date_from: Start date (ISO format)
            date_to: End date (ISO format)
            time_preference: Time preference (morning, afternoon, etc.)
            duration_minutes: Appointment duration
            limit: Maximum slots to return

        Returns:
            List of available time slots
        """
        client = await self._get_client()

        payload: dict = {
            "duration_minutes": duration_minutes,
            "limit": limit,
        }

        if provider_id:
            payload["provider_id"] = provider_id
        if date_from:
            payload["date_from"] = date_from
        if date_to:
            payload["date_to"] = date_to
        if time_preference:
            payload["time_preference"] = time_preference

        try:
            response = await client.post(
                "/api/slots/find",
                json=payload,
                headers={"X-Tenant-ID": tenant_id},
            )
            response.raise_for_status()

            data = response.json()
            slots = data.get("slots", data.get("items", data if isinstance(data, list) else []))
            return [TimeSlot.from_dict(s) for s in slots]

        except httpx.HTTPError as e:
            logger.error(f"Failed to find slots: {e}")
            return []

    # === Bookings ===

    async def create_booking(
        self,
        tenant_id: str,
        slot_id: str,
        patient_name: str,
        patient_phone: Optional[str] = None,
        patient_email: Optional[str] = None,
        reason: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> BookingResult:
        """Create a new booking.

        Args:
            tenant_id: Clinic/tenant identifier
            slot_id: Slot ID to book
            patient_name: Patient's name
            patient_phone: Patient's phone (optional)
            patient_email: Patient's email (optional)
            reason: Reason for visit (optional)
            notes: Additional notes (optional)

        Returns:
            BookingResult with success status
        """
        client = await self._get_client()

        payload: dict = {
            "slot_id": slot_id,
            "patient": {"name": patient_name},
        }

        if patient_phone:
            payload["patient"]["phone"] = patient_phone
        if patient_email:
            payload["patient"]["email"] = patient_email
        if reason:
            payload["reason"] = reason
        if notes:
            payload["notes"] = notes

        try:
            response = await client.post(
                "/api/bookings",
                json=payload,
                headers={"X-Tenant-ID": tenant_id},
            )

            data = response.json()

            if response.status_code in (200, 201):
                return BookingResult(
                    success=True,
                    booking_id=data.get("booking_id", data.get("id")),
                    message=data.get("message", "Booking confirmed"),
                )
            else:
                return BookingResult(
                    success=False,
                    error_code=data.get("error_code", "booking_failed"),
                    message=data.get("message", data.get("error", "Booking failed")),
                    suggestions=data.get("suggestions"),
                    alternative_slots=[
                        TimeSlot.from_dict(s)
                        for s in data.get("alternative_slots", [])
                    ] if data.get("alternative_slots") else None,
                )

        except httpx.HTTPError as e:
            logger.error(f"Failed to create booking: {e}")
            return BookingResult(
                success=False,
                error_code="connection_error",
                message="Unable to connect to scheduling system",
            )

    async def cancel_booking(
        self,
        tenant_id: str,
        booking_id: str,
        reason: Optional[str] = None,
    ) -> BookingResult:
        """Cancel an existing booking.

        Args:
            tenant_id: Clinic/tenant identifier
            booking_id: Booking ID to cancel
            reason: Cancellation reason (optional)

        Returns:
            BookingResult with success status
        """
        client = await self._get_client()

        try:
            params = {"reason": reason} if reason else {}

            response = await client.delete(
                f"/api/bookings/{booking_id}",
                params=params,
                headers={"X-Tenant-ID": tenant_id},
            )

            if response.status_code in (200, 204):
                return BookingResult(
                    success=True,
                    booking_id=booking_id,
                    message="Booking cancelled successfully",
                )
            else:
                data = response.json()
                return BookingResult(
                    success=False,
                    error_code=data.get("error_code", "cancellation_failed"),
                    message=data.get("message", "Cancellation failed"),
                )

        except httpx.HTTPError as e:
            logger.error(f"Failed to cancel booking: {e}")
            return BookingResult(
                success=False,
                error_code="connection_error",
                message="Unable to connect to scheduling system",
            )

    async def get_booking(
        self,
        tenant_id: str,
        booking_id: str,
    ) -> Optional[dict]:
        """Get booking details.

        Args:
            tenant_id: Clinic/tenant identifier
            booking_id: Booking ID to retrieve

        Returns:
            Booking details dict or None
        """
        client = await self._get_client()

        try:
            response = await client.get(
                f"/api/bookings/{booking_id}",
                headers={"X-Tenant-ID": tenant_id},
            )

            if response.status_code == 200:
                return response.json()
            return None

        except httpx.HTTPError as e:
            logger.error(f"Failed to get booking: {e}")
            return None


# Singleton
_client: Optional[CalendarAgentClient] = None


def get_calendar_client() -> CalendarAgentClient:
    """Get singleton CalendarAgentClient."""
    global _client
    if _client is None:
        _client = CalendarAgentClient()
    return _client
