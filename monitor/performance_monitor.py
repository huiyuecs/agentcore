"""
 Highlights:Use Monitor to monitor Agent’s online performance

 Core question: How to use Monitor to monitor the online performance of Agent?

 Answers to this module:
  1.  Real-time collection ——  Pull latest statistics from Orchestrator and ToolManager every N seconds
  2.  Anomaly Detection —— Z-score  Statistical methods, Automatically discover indicator mutations
  3.  Route feedback ——  Write Agent success rate/latency back to Orchestrator,
     Orchestrator _best_agent()  The routing weight will be dynamically adjusted accordingly.
  4. Optimization suggestions ——  Generate actionable optimization suggestions based on rules ( is not empty talk)
  5.  Alarm ——  Log when the threshold is exceeded + Optional Webhook
"""
import asyncio
import logging
import statistics
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

import httpx
from prometheus_client import Counter, Gauge, Histogram, start_http_server

logger = logging.getLogger(__name__)


# ── Data structure ──────────────────────────────────────────────────────────────────

class Severity(Enum):
    INFO     = "info"
    WARNING  = "warning"
    ERROR    = "error"
    CRITICAL = "critical"


@dataclass
class Alert:
    severity:    Severity
    metric:      str
    message:     str
    value:       float
    threshold:   float
    ts:          str = field(default_factory=lambda: datetime.now().isoformat())
    resolved:    bool = False


@dataclass
class Suggestion:
    """ Actionable optimization suggestions."""
    title:       str
    detail:      str
    action:      str    #  Specific operation steps
    priority:    int    # 1-10


# ──  Anomaly detection ──────────────────────────────────────────────────────────────────

class AnomalyDetector:
    """
     Anomaly detection based on sliding window Z-score.

    Z-score = | Current value - mean| / Standard deviation
     If the standard deviation exceeds sensitivity times, it is determined to be abnormal.
    """

    def __init__(self, window: int = 60, sensitivity: float = 2.5):
        self._window      = window
        self._sensitivity = sensitivity
        self._history: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=window))

    def record(self, metric: str, value: float) -> Optional[Dict[str, Any]]:
        """ Record a data point, If exception occurs, exception information will be returned. Otherwise None is returned."""
        buf = self._history[metric]
        buf.append(value)

        if len(buf) < self._window // 2:
            return None  #  Insufficient data,Do not detect

        mean  = statistics.mean(buf)
        stdev = statistics.stdev(buf) if len(buf) > 1 else 0.0
        if stdev == 0:
            return None

        z = abs(value - mean) / stdev
        if z > self._sensitivity:
            return {
                "metric":   metric,
                "value":    value,
                "mean":     mean,
                "z_score":  round(z, 2),
                "severity": "high" if z > self._sensitivity * 1.5 else "medium",
            }
        return None


# ── Performance Monitor ────────────────────────────────────────────────────────────────

class PerformanceMonitor:
    """
    Agent  Online performance monitoring.

     Linkage with Orchestrator:
      Monitor  Collection →  It was found that the success rate of an Agent decreased
The routing_score of the Agent in  →
      Orchestrator.get_stats()  is automatically reduced. →
      _best_agent()  Automatically bypass the Agent when routing

    This is"Use Monitor to monitor online performance
Closed loop of ".
    """

    #  Alarm threshold
    THRESHOLDS = {
        "agent_success_rate":  (0.90, Severity.ERROR,   "less_than"),
        "tool_success_rate":   (0.95, Severity.WARNING,  "less_than"),
        "agent_avg_ms":        (3000, Severity.WARNING,  "greater_than"),
        "tool_avg_ms":         (5000, Severity.ERROR,    "greater_than"),
    }

    def __init__(
        self,
        orchestrator,
        tool_manager,
        interval_s:       float = 10.0,
        webhook_url:      Optional[str] = None,
        prometheus_port:  Optional[int] = None,   # None = Does not start
    ):
        self._orchestrator = orchestrator
        self._tool_manager = tool_manager
        self._interval     = interval_s
        self._webhook      = webhook_url
        self._detector     = AnomalyDetector()

        self._alerts:      List[Alert]      = []
        self._suggestions: List[Suggestion] = []
        self._active       = False
        self._task:        Optional[asyncio.Task] = None

        # Prometheus Indicator( Optional)
        self._prom: Dict[str, Any] = {}
        if prometheus_port:
            self._setup_prometheus(prometheus_port)

    def _setup_prometheus(self, port: int) -> None:
        self._prom = {
            "agent_success_rate": Gauge("agent_success_rate", "Agent Success rate", ["agent"]),
            "agent_latency_ms":   Histogram("agent_latency_ms", "Agent  Delay", ["agent"]),
            "tool_success_rate":  Gauge("tool_success_rate", " Tool success rate", ["tool"]),
            "requests_total":     Counter("requests_total", " Total requests"),
        }
        start_http_server(port)
        logger.info(f"Prometheus  Started: :{port}")

    # ──  Life cycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._task   = asyncio.create_task(self._loop())
        logger.info(f"Monitor  Started, Collection interval {self._interval}s")

    async def stop(self) -> None:
        self._active = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ──  Acquisition loop ──────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._active:
            try:
                await self._collect()
            except Exception as ex:
                logger.error(f"Monitor  Collection exception: {ex}")
            await asyncio.sleep(self._interval)

    async def _collect(self) -> None:
        """
         Collect real-time statistics of Agent and tools, Detection anomaly, Generate suggestions.

        Key: The stats read here are Orchestrator/ToolManager when processing requests
         Real-time updated data,Monitor  No additional points are needed.
        """
        agent_stats = self._orchestrator.get_stats()
        tool_stats  = self._tool_manager.get_stats()
        routing_penalties: Dict[str, float] = {}

        # ── Agent Indicator ────────────────────────────────────────────────────────
        for agent_key, s in agent_stats.items():
            sr  = s["success_rate"]
            ms  = s["avg_ms"]

            #  Anomaly detection
            for metric, value in [("agent_success_rate", sr), ("agent_avg_ms", ms)]:
                anomaly = self._detector.record(f"{metric}:{agent_key}", value)
                if anomaly:
                    logger.warning(f" Anomaly detection [{agent_key}] {metric}={value:.3f} z={anomaly['z_score']}")

            #  Threshold alarm
            self._check_threshold("agent_success_rate", sr, agent_key)
            self._check_threshold("agent_avg_ms", ms, agent_key)

            # Prometheus
            if "agent_success_rate" in self._prom:
                self._prom["agent_success_rate"].labels(agent=agent_key).set(sr)
                self._prom["agent_latency_ms"].labels(agent=agent_key).observe(ms)

            routing_penalties[agent_key] = self._routing_penalty(sr, ms)

        # ──  Tool indicator ──────────────────────────────────────────────────────────
        for tool_name, s in tool_stats.items():
            sr = s["success_rate"]
            ms = s["avg_latency_ms"]
            cf = s["consecutive_fails"]

            self._check_threshold("tool_success_rate", sr, tool_name)
            self._check_threshold("tool_avg_ms", ms, tool_name)

            if "tool_success_rate" in self._prom:
                self._prom["tool_success_rate"].labels(tool=tool_name).set(sr)

            # Continuous failures →  Generate specific recommendations
            if cf >= 3:
                self._add_suggestion(Suggestion(
                    title=f"Tools {tool_name} Continuous failures {cf}  times",
                    detail=f"Success rate {sr:.1%},Average latency {ms:.0f}ms, Fuse status: {s['circuit_state']}",
                    action="1.  Check whether the tool’s dependent services are normal\n2.  View error log\n3.  Consider increasing timeout or downgrade strategy",
                    priority=9,
                ))

        # ── Route optimization suggestions ──────────────────────────────────────────────────────
        updater = getattr(self._orchestrator, "update_routing_penalties", None)
        if updater:
            updater(routing_penalties)
        self._generate_routing_suggestions(agent_stats)

    @staticmethod
    def _routing_penalty(success_rate: float, avg_ms: float) -> float:
        """ Convert online performance to a routing weight reduction coefficient of 0-0.9."""
        penalty = 0.0
        if success_rate < 0.90:
            penalty += min(0.5, (0.90 - success_rate) * 2)
        if avg_ms > 3000:
            penalty += min(0.4, (avg_ms - 3000) / 10000)
        return min(penalty, 0.9)

    def _check_threshold(self, metric: str, value: float, label: str) -> None:
        if metric not in self.THRESHOLDS:
            return
        threshold, severity, operator = self.THRESHOLDS[metric]
        triggered = (operator == "less_than" and value < threshold) or \
                    (operator == "greater_than" and value > threshold)
        if triggered:
            alert = Alert(
                severity=severity,
                metric=f"{metric}:{label}",
                message=f"{label}  {metric} = {value:.3f}, Threshold {threshold}",
                value=value,
                threshold=threshold,
            )
            self._alerts.append(alert)
            logger.warning(f"[{severity.value.upper()}] {alert.message}")
            #  Asynchronously send Webhook( Does not block acquisition loop)
            if self._webhook:
                asyncio.create_task(self._send_webhook(alert))

    def _generate_routing_suggestions(self, agent_stats: Dict[str, Any]) -> None:
        """
         Generate routing optimization suggestions based on Agent's online performance.
        This is Monitor → Orchestrator  The embodiment of feedback closed loop.
        """
        for agent_key, s in agent_stats.items():
            if s["success_rate"] < 0.85 and s["total"] > 10:
                self._add_suggestion(Suggestion(
                    title=f"Agent {agent_key} Success rate is low",
                    detail=f"Success rate {s['success_rate']:.1%},Route Score {s['routing_score']:.3f}",
                    action=(
                        "Orchestrator _best_agent()  The agent's routing weight has been automatically reduced.\n"
                        " Recommendation:1.  Check if system_prompt needs optimization\n"
                        "      2.  Check whether the complexity of this type of problem exceeds the agent's capabilities\n"
                        "      3.  Consider adding Agent instances of the same type"
                    ),
                    priority=8,
                ))

    def _add_suggestion(self, s: Suggestion) -> None:
        # Remove duplicates: The same title will not be added repeatedly
        if not any(x.title == s.title for x in self._suggestions):
            self._suggestions.append(s)
            logger.info(f"Optimization suggestions [P{s.priority}]: {s.title}")

    async def _send_webhook(self, alert: Alert) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                await c.post(self._webhook, json=asdict(alert))  # type: ignore
        except Exception as ex:
            logger.error(f"Webhook Sending failed: {ex}")

    # ──  Query interface ──────────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """ Returns the current monitoring summary, For API layer exposure."""
        return {
            "agent_stats":   self._orchestrator.get_stats(),
            "tool_stats":    self._tool_manager.get_stats(),
            "active_alerts": [asdict(a) for a in self._alerts if not a.resolved][-10:],
            "suggestions":   [
                {"title": s.title, "action": s.action, "priority": s.priority}
                for s in sorted(self._suggestions, key=lambda x: -x.priority)[:5]
            ],
        }
