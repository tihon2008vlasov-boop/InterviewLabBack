from dataclasses import dataclass, field

from fastapi import WebSocket


@dataclass
class ProctorViewer:
    websocket: WebSocket
    name: str
    user_id: str
    watching: bool = False
    media_allowed: bool = False


@dataclass
class ProctorRoom:
    candidate: WebSocket | None = None
    viewers: dict[str, ProctorViewer] = field(default_factory=dict)


class ProctoringHub:
    """In-process signaling hub. Media stays in peer-to-peer WebRTC connections."""

    def __init__(self) -> None:
        self.rooms: dict[str, ProctorRoom] = {}

    def _room(self, session_id: str) -> ProctorRoom:
        return self.rooms.setdefault(session_id, ProctorRoom())

    async def connect_candidate(self, session_id: str, websocket: WebSocket) -> None:
        room = self._room(session_id)
        previous = room.candidate
        room.candidate = websocket
        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=4001, reason="Candidate reconnected")
            except RuntimeError:
                pass
        await self.broadcast_viewers(
            session_id,
            {"type": "candidate_presence", "online": True},
        )

    async def connect_viewer(
        self,
        session_id: str,
        viewer_id: str,
        websocket: WebSocket,
        name: str,
        user_id: str,
    ) -> None:
        self._room(session_id).viewers[viewer_id] = ProctorViewer(
            websocket=websocket,
            name=name,
            user_id=user_id,
        )

    async def disconnect_candidate(self, session_id: str, websocket: WebSocket) -> None:
        room = self.rooms.get(session_id)
        if room is None or room.candidate is not websocket:
            return
        room.candidate = None
        await self.broadcast_viewers(
            session_id,
            {"type": "candidate_presence", "online": False},
        )
        self._clean(session_id)

    async def disconnect_viewer(self, session_id: str, viewer_id: str) -> None:
        room = self.rooms.get(session_id)
        if room is None:
            return
        viewer = room.viewers.pop(viewer_id, None)
        if viewer is not None and room.candidate is not None:
            await self.send_candidate(
                session_id,
                {"type": "viewer_left", "viewer_id": viewer_id},
            )
        self._clean(session_id)

    def _clean(self, session_id: str) -> None:
        room = self.rooms.get(session_id)
        if room is not None and room.candidate is None and not room.viewers:
            self.rooms.pop(session_id, None)

    def candidate_online(self, session_id: str) -> bool:
        room = self.rooms.get(session_id)
        return bool(room and room.candidate)

    def viewer_count(self, session_id: str) -> int:
        room = self.rooms.get(session_id)
        return sum(1 for viewer in room.viewers.values() if viewer.watching) if room else 0

    def set_watching(self, session_id: str, viewer_id: str, watching: bool) -> None:
        room = self.rooms.get(session_id)
        if room and viewer_id in room.viewers:
            room.viewers[viewer_id].watching = watching
            if not watching:
                room.viewers[viewer_id].media_allowed = False

    def allow_media(self, session_id: str, viewer_id: str) -> bool:
        room = self.rooms.get(session_id)
        viewer = room.viewers.get(viewer_id) if room else None
        if viewer is None or not viewer.watching:
            return False
        viewer.media_allowed = True
        return True

    def can_receive_media(self, session_id: str, viewer_id: str) -> bool:
        room = self.rooms.get(session_id)
        viewer = room.viewers.get(viewer_id) if room else None
        return bool(viewer and viewer.watching and viewer.media_allowed)

    async def send_candidate(self, session_id: str, message: dict) -> bool:
        room = self.rooms.get(session_id)
        if room is None or room.candidate is None:
            return False
        try:
            await room.candidate.send_json(message)
            return True
        except RuntimeError:
            return False

    async def send_viewer(self, session_id: str, viewer_id: str, message: dict) -> bool:
        room = self.rooms.get(session_id)
        viewer = room.viewers.get(viewer_id) if room else None
        if viewer is None:
            return False
        try:
            await viewer.websocket.send_json(message)
            return True
        except RuntimeError:
            return False

    async def broadcast_viewers(self, session_id: str, message: dict) -> None:
        room = self.rooms.get(session_id)
        if room is None:
            return
        for viewer in list(room.viewers.values()):
            try:
                await viewer.websocket.send_json(message)
            except RuntimeError:
                continue


proctoring_hub = ProctoringHub()
