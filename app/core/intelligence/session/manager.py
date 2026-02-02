"""Redis-based session management for the intelligence layer."""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from app.config import settings
from app.infra.redis import get_redis, APP_PREFIX
from .models import SessionData
from .state import BookingState, can_transition


def _utcnow() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)

logger = logging.getLogger(__name__)

# Session key prefix (extends existing APP_PREFIX)
SESSION_PREFIX = f"{APP_PREFIX}intelligence:session:"


class SessionManager:
    """
    Redis-based session manager for conversation state.

    Key pattern: receptionist:v1:intelligence:session:{clinic_id}:{session_id}

    Gracefully handles Redis unavailability with in-memory fallback.
    """

    def __init__(self):
        """Initialize session manager."""
        self._ttl = settings.redis_session_ttl  # 30 minutes default
        self._in_memory_fallback: dict[str, SessionData] = {}

    def _key(self, clinic_id: str, session_id: str) -> str:
        """Generate Redis key."""
        return f"{SESSION_PREFIX}{clinic_id}:{session_id}"

    async def create(
        self,
        clinic_id: str,
        session_id: Optional[str] = None,
        patient_id: Optional[str] = None,
    ) -> SessionData:
        """
        Create a new session.

        Args:
            clinic_id: Clinic identifier
            session_id: Session ID (auto-generated if not provided)
            patient_id: Patient ID (optional)

        Returns:
            Created SessionData
        """
        session = SessionData(
            session_id=session_id or str(uuid4()),
            clinic_id=clinic_id,
            patient_id=patient_id,
            state=BookingState.IDLE,
        )

        redis = await get_redis()

        if redis:
            key = self._key(clinic_id, session.session_id)
            await redis.setex(key, self._ttl, session.to_json())
            logger.debug(f"Session created: {session.session_id}")
        else:
            # Fallback to in-memory
            self._in_memory_fallback[session.session_id] = session
            logger.warning(
                f"Redis unavailable, using in-memory fallback for session {session.session_id}"
            )

        return session

    async def get(
        self,
        clinic_id: str,
        session_id: str,
    ) -> Optional[SessionData]:
        """
        Get session by ID.

        Args:
            clinic_id: Clinic identifier
            session_id: Session identifier

        Returns:
            SessionData or None if not found
        """
        redis = await get_redis()

        if redis:
            key = self._key(clinic_id, session_id)
            data = await redis.get(key)

            if data:
                return SessionData.from_json(data)
            return None
        else:
            # Fallback to in-memory
            return self._in_memory_fallback.get(session_id)

    async def get_or_create(
        self,
        clinic_id: str,
        session_id: Optional[str] = None,
    ) -> SessionData:
        """
        Get existing session or create new one.

        Args:
            clinic_id: Clinic identifier
            session_id: Session ID (optional)

        Returns:
            Existing or new SessionData
        """
        if session_id:
            session = await self.get(clinic_id, session_id)
            if session:
                # Refresh TTL
                await self._refresh_ttl(clinic_id, session_id)
                return session

        return await self.create(clinic_id)

    async def save(self, session: SessionData) -> bool:
        """
        Save session to Redis.

        Args:
            session: SessionData to save

        Returns:
            True if saved successfully
        """
        session.updated_at = _utcnow()

        redis = await get_redis()

        if redis:
            key = self._key(session.clinic_id, session.session_id)
            await redis.setex(key, self._ttl, session.to_json())
            logger.debug(f"Session saved: {session.session_id}")
            return True
        else:
            # Fallback to in-memory
            self._in_memory_fallback[session.session_id] = session
            return True

    async def update(
        self,
        session: SessionData,
        refresh_ttl: bool = True,
    ) -> bool:
        """
        Update session in Redis.

        Args:
            session: SessionData to update
            refresh_ttl: Whether to refresh TTL

        Returns:
            True if updated successfully
        """
        session.updated_at = _utcnow()

        redis = await get_redis()

        if redis:
            key = self._key(session.clinic_id, session.session_id)

            if refresh_ttl:
                await redis.setex(key, self._ttl, session.to_json())
            else:
                await redis.set(key, session.to_json(), keepttl=True)

            logger.debug(f"Session updated: {session.session_id}")
            return True
        else:
            # Fallback to in-memory
            self._in_memory_fallback[session.session_id] = session
            return True

    async def delete(
        self,
        clinic_id: str,
        session_id: str,
    ) -> bool:
        """
        Delete a session.

        Args:
            clinic_id: Clinic identifier
            session_id: Session identifier

        Returns:
            True if deleted
        """
        redis = await get_redis()

        if redis:
            key = self._key(clinic_id, session_id)
            deleted = await redis.delete(key)

            if deleted:
                logger.debug(f"Session deleted: {session_id}")

            return bool(deleted)
        else:
            # Fallback to in-memory
            if session_id in self._in_memory_fallback:
                del self._in_memory_fallback[session_id]
                return True
            return False

    async def update_state(
        self,
        clinic_id: str,
        session_id: str,
        new_state: BookingState,
    ) -> Optional[SessionData]:
        """
        Update session state with transition validation.

        Args:
            clinic_id: Clinic identifier
            session_id: Session identifier
            new_state: Target state

        Returns:
            Updated SessionData or None if transition invalid
        """
        session = await self.get(clinic_id, session_id)

        if session is None:
            logger.warning(f"Session not found: {session_id}")
            return None

        if not can_transition(session.state, new_state):
            logger.warning(
                f"Invalid transition: {session.state.value} -> {new_state.value}"
            )
            return None

        session.previous_state = session.state
        session.state = new_state
        await self.update(session)

        logger.debug(f"Session {session_id} transitioned to {new_state.value}")
        return session

    async def update_collected(
        self,
        clinic_id: str,
        session_id: str,
        updates: dict,
    ) -> Optional[SessionData]:
        """
        Update collected data in session.

        Args:
            clinic_id: Clinic identifier
            session_id: Session identifier
            updates: Data to merge into collected_data

        Returns:
            Updated SessionData or None if not found
        """
        session = await self.get(clinic_id, session_id)

        if session is None:
            return None

        for key, value in updates.items():
            if value is not None:
                session.collected_data[key] = value

        await self.update(session)
        return session

    async def add_message(
        self,
        clinic_id: str,
        session_id: str,
        role: str,
        content: str,
        intent: Optional[str] = None,
    ) -> Optional[SessionData]:
        """
        Add a message to session history.

        Args:
            clinic_id: Clinic identifier
            session_id: Session identifier
            role: "user" or "assistant"
            content: Message content
            intent: Detected intent (optional)

        Returns:
            Updated SessionData or None if not found
        """
        session = await self.get(clinic_id, session_id)

        if session is None:
            return None

        # Import here to avoid circular imports
        from app.core.intelligence.intent.types import Intent

        intent_enum = None
        if intent:
            try:
                intent_enum = Intent(intent)
            except ValueError:
                pass

        session.add_turn(role, content, intent=intent_enum)
        await self.update(session)

        return session

    async def _refresh_ttl(self, clinic_id: str, session_id: str) -> bool:
        """Refresh session TTL."""
        redis = await get_redis()

        if redis:
            key = self._key(clinic_id, session_id)
            return await redis.expire(key, self._ttl)

        return True  # In-memory doesn't have TTL


# Singleton
_manager: Optional[SessionManager] = None


async def get_session_manager() -> SessionManager:
    """Get singleton SessionManager."""
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager
