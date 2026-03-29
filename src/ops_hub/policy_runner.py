"""Background runner for workflow policy evaluation."""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field

from ops_hub.core.config import Settings
from ops_hub.core.container import ServiceContainer


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WorkflowPolicyRunner:
    """Run workflow policy evaluation on a fixed interval in the background."""

    settings: Settings
    container: ServiceContainer
    thread: threading.Thread | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)

    def start(self) -> None:
        """Start the background runner when enabled."""
        if not self.settings.enable_workflow_policy_runner:
            return
        if self.thread is not None:
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run_loop, name="ops-hub-policy-runner", daemon=True)
        self.thread.start()
        logger.info(
            "Workflow policy runner started",
            extra={"interval_seconds": self.settings.workflow_policy_interval_seconds},
        )

    def stop(self) -> None:
        """Stop the background runner."""
        if self.thread is None:
            return
        self.stop_event.set()
        self.thread.join(timeout=2)
        self.thread = None

    def _run_loop(self) -> None:
        """Run periodic policy refresh until shutdown."""
        self._run_once()
        while not self.stop_event.wait(self.settings.workflow_policy_interval_seconds):
            self._run_once()

    def _run_once(self) -> None:
        try:
            asyncio.run(self.container.workflow_state_service.run_policy_cycle())
        except Exception:
            logger.exception("Workflow policy cycle failed")


def build_policy_runner(*, settings: Settings, container: ServiceContainer) -> WorkflowPolicyRunner:
    """Construct the background workflow policy runner."""
    return WorkflowPolicyRunner(settings=settings, container=container)
