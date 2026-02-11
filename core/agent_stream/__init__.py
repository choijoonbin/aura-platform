"""
Agent Stream Module (Prompt C)

Dashboard "Agent Execution Stream"을 실제 에이전트/워크플로우 이벤트로 채우기.
Aura → Synapse REST push: POST /api/synapse/agent/events
"""

from core.agent_stream.constants import (
    STAGE_GROUP_ACTION,
    STAGE_GROUP_DETECTION,
    STAGE_GROUP_REASONING,
    STAGE_TO_GROUP,
)
from core.agent_stream.metadata import format_metadata
from core.agent_stream.schemas import AgentEvent, AgentStreamStage
from core.agent_stream.writer import (
    AgentStreamWriter,
    get_agent_stream_writer,
)

__all__ = [
    "AgentEvent",
    "AgentStreamStage",
    "AgentStreamWriter",
    "format_metadata",
    "get_agent_stream_writer",
    "STAGE_GROUP_ACTION",
    "STAGE_GROUP_DETECTION",
    "STAGE_GROUP_REASONING",
    "STAGE_TO_GROUP",
]
