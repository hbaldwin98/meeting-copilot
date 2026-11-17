"""Values that cross module seams. Kept dumb on purpose."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np

Channel = Literal["me", "them"]
SAMPLE_RATE = 16_000


@dataclass(slots=True)
class AudioFrame:
    channel: Channel
    t: float  # session-relative seconds at the start of this frame
    pcm: np.ndarray  # float32, mono, SAMPLE_RATE


@dataclass(slots=True)
class Utterance:
    channel: Channel
    t0: float
    t1: float
    text: str
    final: bool = True  # False = partial; replaced by later partials / the final

    def to_event(self) -> dict[str, Any]:
        return {"type": "transcript", **asdict(self)}


@dataclass(slots=True)
class AgentEvent:
    """Everything the assistant tells the outside world.

    type is one of:
      card           {id, headline, body_md, sources[], task_id?}
      task.started   {id, title, kind}
      task.progress  {id, note}
      task.done      {id, card_id}
      task.failed    {id, error}
      task.cancelled {id}
      status         {state, detail}
    """

    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_event(self) -> dict[str, Any]:
        return {"type": self.type, **self.data}
