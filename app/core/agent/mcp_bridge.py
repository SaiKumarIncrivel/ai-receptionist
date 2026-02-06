"""
MCP Tool Bridge for Calendar Agent.

Converts Calendar Agent's functionality to Anthropic tool_use format
and executes tool calls via HTTP until proper MCP transport is available.

API Endpoints (Calendar Agent v1):
- POST /v1/slots/search - FindSlotsRequest
- POST /v1/bookings - BookAppointmentRequest
- GET /v1/bookings/{booking_id} - returns BookingResponse
- DELETE /v1/bookings/{booking_id} - CancelBookingRequest in body
- GET /v1/bookings/confirmation/{confirmation_number} - returns BookingResponse
- GET /v1/providers - list active providers
"""

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class CalendarToolBridge:
    """
    Bridge between Claude tool_use and Calendar Agent HTTP API.

    This provides Calendar Agent tools in Anthropic tool format and
    executes tool calls by routing them to the appropriate HTTP endpoints.

    Future: Will be replaced with direct MCP/SSE transport.
    """

    def __init__(self, base_url: Optional[str] = None, timeout: float = 30.0):
        """
        Initialize the bridge.

        Args:
            base_url: Calendar Agent base URL (defaults to settings)
            timeout: Request timeout in seconds
        """
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

    def get_anthropic_tools(self) -> list[dict]:
        """
        Return Calendar Agent tools in Anthropic tool_use format.

        These tool definitions are optimized for Claude's understanding,
        with detailed descriptions that help Claude know when and how
        to use each tool.
        """
        return [
            {
                "name": "list_providers",
                "description": (
                    "List available doctors and providers at the clinic. "
                    "Use this when the patient hasn't specified a doctor, "
                    "or you need to find a doctor by specialty. "
                    "Returns provider names, IDs, and their specialties."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "specialty": {
                            "type": "string",
                            "description": (
                                "Optional specialty filter. Examples: 'cardiology', "
                                "'pediatrics', 'general practice'. Leave empty to list all."
                            ),
                        },
                    },
                },
            },
            {
                "name": "find_optimal_slots",
                "description": (
                    "Find available appointment slots for booking. "
                    "Use this to check availability for a specific provider or date range. "
                    "Returns a list of available time slots with slot IDs needed for booking. "
                    "ALWAYS call this before attempting to book - never assume availability."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "provider_name": {
                            "type": "string",
                            "description": (
                                "Doctor/provider name. Can be partial, e.g., 'Smith' or 'Dr. Patel'. "
                                "If not provided, searches across all providers."
                            ),
                        },
                        "provider_id": {
                            "type": "string",
                            "description": (
                                "Provider ID if known (from list_providers). "
                                "More precise than name matching."
                            ),
                        },
                        "date_from": {
                            "type": "string",
                            "description": (
                                "Start date in ISO format YYYY-MM-DD. "
                                "Use this for 'tomorrow', 'next week', etc."
                            ),
                        },
                        "date_to": {
                            "type": "string",
                            "description": (
                                "End date in ISO format YYYY-MM-DD. "
                                "If not provided, defaults to same as date_from."
                            ),
                        },
                        "time_preference": {
                            "type": "string",
                            "enum": ["morning", "afternoon", "evening", "any"],
                            "description": (
                                "Preferred time of day. "
                                "'morning' = before noon, "
                                "'afternoon' = noon to 5pm, "
                                "'evening' = after 5pm."
                            ),
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "default": 30,
                            "description": "Appointment duration in minutes. Default is 30.",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 5,
                            "description": "Maximum number of slots to return. Default is 5.",
                        },
                    },
                },
            },
            {
                "name": "book_appointment",
                "description": (
                    "Book an appointment slot. REQUIRES: "
                    "(1) A valid slot_id from find_optimal_slots, "
                    "(2) Patient's name. "
                    "ALWAYS get explicit patient confirmation before calling this. "
                    "Returns booking confirmation with booking ID."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "slot_id": {
                            "type": "string",
                            "description": "The slot ID to book (from find_optimal_slots results).",
                        },
                        "patient_name": {
                            "type": "string",
                            "description": "Patient's full name.",
                        },
                        "patient_phone": {
                            "type": "string",
                            "description": "Patient's phone number (optional but recommended).",
                        },
                        "patient_email": {
                            "type": "string",
                            "description": "Patient's email address (optional).",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Reason for the appointment (e.g., 'checkup', 'back pain').",
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "default": 30,
                            "description": "Appointment duration in minutes. Default is 30.",
                        },
                    },
                    "required": ["slot_id", "patient_name"],
                },
            },
            {
                "name": "cancel_appointment",
                "description": (
                    "Cancel an existing appointment. "
                    "Requires the booking ID which the patient should provide. "
                    "ALWAYS confirm cancellation with the patient before calling this."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "booking_id": {
                            "type": "string",
                            "description": "The booking ID to cancel.",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Reason for cancellation (optional).",
                        },
                    },
                    "required": ["booking_id"],
                },
            },
            {
                "name": "get_booking",
                "description": (
                    "Get details of an existing appointment. "
                    "Use this to check booking status or verify appointment details. "
                    "Can look up by booking ID (UUID) or confirmation number (6-char code)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "booking_id": {
                            "type": "string",
                            "description": "The booking ID (UUID) to look up.",
                        },
                        "confirmation_number": {
                            "type": "string",
                            "description": "The 6-character confirmation number to look up.",
                        },
                    },
                    # No required - either one works
                },
            },
        ]

    async def execute_tool(
        self,
        tool_name: str,
        tool_input: dict,
        tenant_id: str,
    ) -> dict:
        """
        Execute a tool call against Calendar Agent's HTTP API.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Tool input parameters
            tenant_id: Clinic/tenant identifier

        Returns:
            Tool result as a dict (serializable to JSON for tool_result block)
        """
        try:
            match tool_name:
                case "list_providers":
                    return await self._list_providers(tenant_id, tool_input)
                case "find_optimal_slots":
                    return await self._find_slots(tenant_id, tool_input)
                case "book_appointment":
                    return await self._book(tenant_id, tool_input)
                case "cancel_appointment":
                    return await self._cancel(tenant_id, tool_input)
                case "get_booking":
                    return await self._get_booking(tenant_id, tool_input)
                case _:
                    return {
                        "error": "unknown_tool",
                        "message": f"Unknown tool: {tool_name}",
                    }
        except Exception as e:
            logger.exception(f"Tool execution failed: {tool_name}")
            return {
                "error": "execution_failed",
                "message": str(e),
            }

    async def _list_providers(self, tenant_id: str, input: dict) -> dict:
        """List providers via HTTP API."""
        client = await self._get_client()

        try:
            response = await client.get(
                "/v1/providers",
                headers={"X-Tenant-ID": tenant_id},
            )
            response.raise_for_status()

            data = response.json()
            if isinstance(data, list):
                providers = data
            else:
                providers = data.get("providers", data.get("items", []))

            # Filter by specialty if provided
            specialty = input.get("specialty")
            if specialty:
                specialty_lower = specialty.lower()
                providers = [
                    p for p in providers
                    if p.get("specialty") and specialty_lower in p["specialty"].lower()
                ]

            return {
                "providers": [
                    {
                        "id": p.get("id", ""),
                        "name": p.get("name", ""),
                        "email": p.get("email", ""),
                        "specialty": p.get("specialty", "General"),
                    }
                    for p in providers
                ],
                "count": len(providers),
            }

        except httpx.HTTPError as e:
            logger.error(f"Failed to list providers: {e}")
            return {
                "error": "api_error",
                "message": "Unable to fetch provider list",
            }

    async def _find_slots(self, tenant_id: str, input: dict) -> dict:
        """Find available slots via HTTP API."""
        client = await self._get_client()

        # Calendar Agent accepts name, alias, or UUID in "provider" field
        provider_query = input.get("provider_id") or input.get("provider_name", "")

        # Map time_preference to boolean flags
        time_pref = input.get("time_preference", "any")
        prefer_morning = time_pref == "morning"
        prefer_afternoon = time_pref in ("afternoon", "evening")

        date_from = input.get("date_from", "")
        date_to = input.get("date_to", date_from)

        payload: dict[str, Any] = {
            "provider": provider_query,
            "start_date": date_from,
            "end_date": date_to,
            "prefer_morning": prefer_morning,
            "prefer_afternoon": prefer_afternoon,
            "duration_minutes": input.get("duration_minutes", 30),
            "max_results": input.get("limit", 5),
        }

        try:
            response = await client.post(
                "/v1/slots/search",
                json=payload,
                headers={"X-Tenant-ID": tenant_id},
            )
            response.raise_for_status()

            data = response.json()

            # Calendar Agent returns FindSlotsResponse with provider and slots
            provider_data = data.get("provider")
            slots_raw = data.get("slots", [])

            slots = [
                {
                    "slot_id": s.get("slot_id", ""),
                    "provider_id": provider_data.get("id", "") if provider_data else "",
                    "provider_name": provider_data.get("name", "") if provider_data else "",
                    "start_time": s.get("start", ""),
                    "end_time": s.get("end", ""),
                    "display_time": s.get("display_time", ""),
                    "duration_minutes": s.get("duration_minutes", 30),
                    "score": s.get("score", 0),
                }
                for s in slots_raw
            ]

            if not slots:
                result: dict[str, Any] = {
                    "slots": [],
                    "count": 0,
                    "message": data.get("message") or "No available slots found.",
                }
                # Include next_available_after if Calendar Agent provides it
                if data.get("next_available_after"):
                    result["next_available_after"] = data["next_available_after"]
                return result

            return {
                "slots": slots,
                "count": len(slots),
                "provider": provider_data,
            }

        except httpx.HTTPError as e:
            logger.error(f"Failed to find slots: {e}")
            return {
                "error": "api_error",
                "message": "Unable to search for available slots",
            }

    async def _book(self, tenant_id: str, input: dict) -> dict:
        """Create booking via HTTP API."""
        client = await self._get_client()

        if not input.get("slot_id"):
            return {
                "error": "missing_slot_id",
                "message": "slot_id is required to book an appointment",
            }
        if not input.get("patient_name"):
            return {
                "error": "missing_patient_name",
                "message": "patient_name is required to book an appointment",
            }

        # Parse slot_id format: "{provider_uuid}:{start_time_iso}"
        # Example: "123e4567-e89b-12d3-a456-426614174000:2025-02-07T14:15:00"
        slot_id = input["slot_id"]
        provider_id = ""
        start_time_str = ""

        try:
            # Find the boundary between UUID and datetime
            # UUID format: 8-4-4-4-12 chars = 36 chars total with hyphens
            # Look for the pattern where date starts (YYYY-MM-DD)
            if "T" in slot_id:
                # Find where the ISO date starts (look for :YYYY- pattern)
                import re
                match = re.search(r":(\d{4}-\d{2}-\d{2}T)", slot_id)
                if match:
                    split_pos = match.start()
                    provider_id = slot_id[:split_pos]
                    start_time_str = slot_id[split_pos + 1:]
                else:
                    # Fallback: assume first 36 chars are UUID
                    provider_id = slot_id[:36]
                    start_time_str = slot_id[37:] if len(slot_id) > 37 else ""
            else:
                # No T found, might be a different format
                provider_id = input.get("provider_id", slot_id)
                start_time_str = input.get("start_time", "")
        except Exception:
            # Fallback: provider_id might be passed separately
            provider_id = input.get("provider_id", slot_id)
            start_time_str = input.get("start_time", "")

        # Calculate end_time from duration
        duration = input.get("duration_minutes", 30)
        end_time_str = ""

        try:
            start_dt = datetime.fromisoformat(start_time_str)
            end_dt = start_dt + timedelta(minutes=duration)
            end_time_str = end_dt.isoformat()
        except Exception:
            end_time_str = start_time_str  # Fallback, will likely error

        # Generate idempotency key from slot + patient
        idem_source = f"{slot_id}:{input['patient_name']}:{tenant_id}"
        idempotency_key = hashlib.sha256(idem_source.encode()).hexdigest()[:16]

        payload: dict[str, Any] = {
            "provider_id": provider_id,
            "start_time": start_time_str,
            "end_time": end_time_str,
            "patient_name": input["patient_name"],
            "idempotency_key": idempotency_key,
            "timezone": "America/New_York",
        }

        if input.get("patient_phone"):
            payload["patient_phone"] = input["patient_phone"]
        if input.get("patient_email"):
            payload["patient_email"] = input["patient_email"]
        if input.get("reason"):
            payload["reason"] = input["reason"]

        try:
            response = await client.post(
                "/v1/bookings",
                json=payload,
                headers={"X-Tenant-ID": tenant_id},
            )

            data = response.json()

            if response.status_code in (200, 201) and data.get("success", True):
                booking = data.get("booking", data)
                return {
                    "success": True,
                    "booking_id": booking.get("id", data.get("id")),
                    "confirmation_number": booking.get("confirmation_number", ""),
                    "message": data.get("message", "Appointment booked successfully"),
                    "confirmation": {
                        "provider_name": booking.get("provider_name", ""),
                        "start_time": booking.get("start_time", start_time_str),
                        "patient_name": input["patient_name"],
                        "confirmation_number": booking.get("confirmation_number", ""),
                    },
                }
            else:
                return {
                    "success": False,
                    "error": data.get("error_code", "booking_failed"),
                    "message": data.get("error", data.get("message", "Booking failed")),
                    "alternatives": [
                        {
                            "start_time": s.get("start", s.get("start_time", "")),
                            "end_time": s.get("end", s.get("end_time", "")),
                        }
                        for s in data.get("alternatives", [])
                    ],
                }

        except httpx.HTTPError as e:
            logger.error(f"Failed to create booking: {e}")
            return {
                "success": False,
                "error": "connection_error",
                "message": "Unable to connect to scheduling system",
            }

    async def _cancel(self, tenant_id: str, input: dict) -> dict:
        """Cancel booking via HTTP API."""
        client = await self._get_client()

        booking_id = input.get("booking_id")
        if not booking_id:
            return {
                "error": "missing_booking_id",
                "message": "booking_id is required to cancel an appointment",
            }

        try:
            # Calendar Agent expects reason in request body, not params
            body = None
            if input.get("reason"):
                body = {"reason": input["reason"]}

            response = await client.delete(
                f"/v1/bookings/{booking_id}",
                json=body,
                headers={"X-Tenant-ID": tenant_id},
            )

            if response.status_code in (200, 204):
                return {
                    "success": True,
                    "booking_id": booking_id,
                    "message": "Appointment cancelled successfully",
                }
            else:
                data = response.json() if response.content else {}
                return {
                    "success": False,
                    "error": data.get("error_code", "cancellation_failed"),
                    "message": data.get("message", "Unable to cancel appointment"),
                }

        except httpx.HTTPError as e:
            logger.error(f"Failed to cancel booking: {e}")
            return {
                "success": False,
                "error": "connection_error",
                "message": "Unable to connect to scheduling system",
            }

    async def _get_booking(self, tenant_id: str, input: dict) -> dict:
        """Get booking details via HTTP API."""
        client = await self._get_client()

        booking_id = input.get("booking_id")
        confirmation_number = input.get("confirmation_number")

        if not booking_id and not confirmation_number:
            return {
                "error": "missing_identifier",
                "message": "booking_id or confirmation_number is required",
            }

        try:
            if booking_id:
                url = f"/v1/bookings/{booking_id}"
            else:
                url = f"/v1/bookings/confirmation/{confirmation_number}"

            response = await client.get(
                url,
                headers={"X-Tenant-ID": tenant_id},
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "found": True,
                    "booking": data,
                }
            elif response.status_code == 404:
                identifier = booking_id or confirmation_number
                return {
                    "found": False,
                    "message": f"No booking found with: {identifier}",
                }
            else:
                return {
                    "error": "api_error",
                    "message": "Unable to retrieve booking details",
                }

        except httpx.HTTPError as e:
            logger.error(f"Failed to get booking: {e}")
            return {
                "error": "connection_error",
                "message": "Unable to connect to scheduling system",
            }


# Singleton
_bridge: Optional[CalendarToolBridge] = None


def get_calendar_bridge() -> CalendarToolBridge:
    """Get singleton CalendarToolBridge."""
    global _bridge
    if _bridge is None:
        _bridge = CalendarToolBridge()
    return _bridge
