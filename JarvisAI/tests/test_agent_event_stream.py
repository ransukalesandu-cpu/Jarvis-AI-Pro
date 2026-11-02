"""Tests for the sequenced, replayable task progress stream."""

import unittest

from agent.events import AgentEvent, EventBus
from agent.models import TaskState


class EventStreamTests(unittest.TestCase):
    def test_published_events_receive_monotonic_sequence_numbers(self):
        bus = EventBus()
        bus.publish(AgentEvent(kind="started", state=TaskState.RUNNING))
        bus.publish(AgentEvent(kind="progress", state=TaskState.RUNNING))

        events = bus.events_since(0)

        self.assertEqual([event.sequence for event in events], [1, 2])
        self.assertEqual(events[1].to_dict()["sequence"], 2)

    def test_cursor_returns_only_new_events(self):
        bus = EventBus()
        bus.publish(AgentEvent(kind="one"))
        bus.publish(AgentEvent(kind="two"))

        events = bus.events_since(1)

        self.assertEqual([event.kind for event in events], ["two"])

    def test_stream_waits_for_a_new_event(self):
        import threading
        import time

        bus = EventBus()
        publisher = threading.Thread(
            target=lambda: (time.sleep(0.02), bus.publish(AgentEvent(kind="live"))),
            daemon=True,
        )
        publisher.start()
        events = bus.events_since(0, timeout=1.0)
        publisher.join(timeout=1.0)

        self.assertEqual([event.kind for event in events], ["live"])

    def test_stream_history_remains_bounded(self):
        bus = EventBus(history=8)
        for index in range(20):
            bus.publish(AgentEvent(kind=str(index)))

        events = bus.events_since(0)

        self.assertEqual(len(events), 8)
        self.assertEqual(events[0].sequence, 13)
        self.assertEqual(events[-1].sequence, 20)


if __name__ == "__main__":
    unittest.main()
