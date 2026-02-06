"""
MCP Tool Bridge for Calendar Agent.

Converts Calendar Agent's functionality to Anthropic tool_use format
and executes tool calls via HTTP until proper MCP transport is available.
"""

import json
import logging
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
                    "Requires the booking ID."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "booking_id": {
                            "type": "string",
                            "description": "The booking ID to look up.",
                        },
                    },
                    "required": ["booking_id"],
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
                "/api/providers",
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

        # Build request payload
        payload: dict[str, Any] = {
            "duration_minutes": input.get("duration_minutes", 30),
            "limit": input.get("limit", 5),
        }

        # Handle provider - try ID first, then resolve name
        if input.get("provider_id"):
            payload["provider_id"] = input["provider_id"]
        elif input.get("provider_name"):
            # Try to resolve name to ID
            provider_id = await self._resolve_provider(tenant_id, input["provider_name"])
            if provider_id:
                payload["provider_id"] = provider_id
            # If not resolved, still send name - API might handle it

        if input.get("date_from"):
            payload["date_from"] = input["date_from"]
        if input.get("date_to"):
            payload["date_to"] = input["date_to"]
        if input.get("time_preference"):
            payload["time_preference"] = input["time_preference"]

        try:
            response = await client.post(
                "/api/slots/find",
                json=payload,
                headers={"X-Tenant-ID": tenant_id},
            )
            response.raise_for_status()

            data = response.json()
            slots_raw = data.get("slots", data.get("items", data if isinstance(data, list) else []))

            slots = [
                {
                    "slot_id": s.get("slot_id", s.get("id", "")),
                    "provider_id": s.get("provider_id", ""),
                    "provider_name": s.get("provider_name", ""),
                    "start_time": s.get("start_time", s.get("start", "")),
                    "end_time": s.get("end_time", s.get("end", "")),
                    "duration_minutes": s.get("duration_minutes", 30),
                }
                for s in slots_raw
            ]

            if not slots:
                return {
                    "slots": [],
                    "count": 0,
                    "message": "No available slots found for the specified criteria.",
                    "suggestions": [
                        "Try a different date",
                        "Try a different provider",
                        "Try a different time preference",
                    ],
                }

            return {
                "slots": slots,
                "count": len(slots),
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

        # Validate required fields
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

        payload: dict[str, Any] = {
            "slot_id": input["slot_id"],
            "patient": {
                "name": input["patient_name"],
            },
        }

        if input.get("patient_phone"):
            payload["patient"]["phone"] = input["patient_phone"]
        if input.get("patient_email"):
            payload["patient"]["email"] = input["patient_email"]
        if input.get("reason"):
            payload["reason"] = input["reason"]

        try:
            response = await client.post(
                "/api/bookings",
                json=payload,
                headers={"X-Tenant-ID": tenant_id},
            )

            data = response.json()

            if response.status_code in (200, 201):
                return {
                    "success": True,
                    "booking_id": data.get("booking_id", data.get("id")),
                    "message": data.get("message", "Appointment booked successfully"),
                    "confirmation": {
                        "provider_name": data.get("provider_name"),
                        "start_time": data.get("start_time"),
                        "patient_name": input["patient_name"],
                    },
                }
            else:
                return {
                    "success": False,
                    "error": data.get("error_code", "booking_failed"),
                    "message": data.get("message", data.get("error", "Booking failed")),
                    "suggestions": data.get("suggestions", [
                        "The slot may no longer be available",
                        "Try searching for new slots",
                    ]),
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
            params = {}
            if input.get("reason"):
                params["reason"] = input["reason"]

            response = await client.delete(
                f"/api/bookings/{booking_id}",
                params=params,
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
        if not booking_id:
            return {
                "error": "missing_booking_id",
                "message": "booking_id is required",
            }

        try:
            response = await client.get(
                f"/api/bookings/{booking_id}",
                headers={"X-Tenant-ID": tenant_id},
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "found": True,
                    "booking": data,
                }
            elif response.status_code == 404:
                return {
                    "found": False,
                    "message": f"No booking found with ID: {booking_id}",
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

    async def _resolve_provider(self, tenant_id: str, name: str) -> Optional[str]:
        """Try to resolve a provider name to ID."""
        try:
            result = await self._list_providers(tenant_id, {})
            providers = result.get("providers", [])

            name_lower = name.lower()
            for provider in providers:
                if name_lower in provider.get("name", "").lower():
                    return provider.get("id")

            return None
        except Exception:
            return None


# Singleton
_bridge: Optional[CalendarToolBridge] = None


def get_calendar_bridge() -> CalendarToolBridge:
    """Get singleton CalendarToolBridge."""
    global _bridge
    if _bridge is None:
        _bridge = CalendarToolBridge()
    return _bridge
