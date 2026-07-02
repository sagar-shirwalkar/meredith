"""
Agent core: the main ReAct (Reason + Act) loop.

This is the orchestrator that ties together all subsystems:
  - LLM client for generation
  - Tool registry + router for execution
  - Context manager for the context window
  - Planner for task decomposition
  - Verifier for post-step checks
  - Recovery for loop detection and escape

The loop:
  1. Build context → send to LLM
  2. Parse response (text + optional tool calls)
  3. Execute tool calls via the router
  4. Observe results, update state
  5. Check for loops → recover if needed
  6. Verify step quality
  7. Repeat until task done or max steps
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from coding_agent.agent.planner import HierarchicalPlanner, Planner
from coding_agent.agent.verifier import Verifier
from coding_agent.config import AppConfig
from coding_agent.context.budget import TokenBudget
from coding_agent.context.compactor import ContextCompactor
from coding_agent.context.manager import ContextManager
from coding_agent.llm.base import LLMClient, StreamEvent
from coding_agent.llm.local import LocalLLMClient
from coding_agent.memory.store import MemoryStore
from coding_agent.rag.retriever import Retriever
from coding_agent.recovery.detector import LoopDetector
from coding_agent.recovery.meta_thinker import MetaThinker
from coding_agent.recovery.strategies import LoopRecovery
from coding_agent.tools.base import ToolRegistry
from coding_agent.tools.preferences import ToolPreferences
from coding_agent.tools.router import ToolRouter
from coding_agent.types import (
    AgentState,
    Message,
    PlanPhase,
    RecoveryAction,
    Role,
    RuntimeTier,
    Step,
    ToolCall,
    ToolResult,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# System prompt templates
# ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT_BASE = """\
You are an expert coding agent. You can read, write, and edit files; search code; \
run commands; and browse the web to accomplish coding tasks.

## Core Rules
1. Think step by step before acting. Write your reasoning, then choose a tool.
2. Prefer `edit_file` over `write_file` for modifying existing files.
3. Prefer `search_code` / `find_symbols` over `read_file` for locating code.
4. After editing a file, verify with `get_diagnostics` or run relevant tests.
5. Never read an entire large file when you only need a specific section.
6. If you're stuck or unsure, explain the problem clearly and ask for guidance.

## Current Task
{task_description}

{subtask_section}
"""

_SUBTASK_SECTION = """\
## Current Subtask (#{subtask_id} of {total})
{subtask_description}
Files likely relevant: {files}
"""

_RECOVERY_INJECTION = """\
⚠️ LOOP DETECTED ({loop_type}): {message}

You must take a DIFFERENT approach. {suggestion}
"""


# ──────────────────────────────────────────────────────────────
# AgentCore
# ──────────────────────────────────────────────────────────────


class AgentCore:
    """
    Main agent orchestrator.

    Usage::

        async with AgentCore(config, llm, task) as agent:
            success = await agent.run()
    """

    def __init__(
        self,
        config: AppConfig,
        llm: LLMClient,
        task: str,
    ) -> None:
        self.config = config
        self.llm = llm
        self.task = task

        # Mutable state
        self.state = AgentState(task=task)

        # Runtime tier for graceful degradation
        self._tier: RuntimeTier = RuntimeTier.LARGE

        # Context compactor (ACC)
        self._compactor: ContextCompactor | None = None

        # Subsystems — initialised in start() to allow async setup
        self._planner: Planner | None = None
        self._verifier: Verifier | None = None
        self._context: ContextManager | None = None
        self._budget: TokenBudget | None = None
        self._tools: ToolRegistry | None = None
        self._router: ToolRouter | None = None
        self._recovery_detector: LoopDetector | None = None
        self._recovery_strategies: LoopRecovery | None = None
        self._retriever: Retriever | None = None
        self._memory: MemoryStore | None = None

        # Conversation history (full fidelity for LLM calls)
        self._messages: list[Message] = []

        # Track consecutive recovery attempts
        self._recovery_attempts = 0

        # Concurrent verification: background task from previous step
        self._pending_verification: asyncio.Task[Any] | None = None

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self) -> None:
        """
        Initialise all subsystems.

        Called automatically by the context manager, but can also
        be called manually if you prefer explicit lifecycle control.
        """
        cfg = self.config

        # Token budget
        self._budget = TokenBudget(
            total=cfg.context.max_tokens,
            step_allocations=cfg.budget.step_allocations,
            max_fraction_per_step=cfg.budget.max_fraction_per_step,
        )

        if cfg.agent.planner_type == "hierarchical":
            self._planner = HierarchicalPlanner(llm=self.llm, config=cfg)
        elif cfg.agent.planner_type == "tree_of_thought":
            self._planner = Planner(llm=self.llm, config=cfg, strategy="tree_of_thought")
        else:
            self._planner = Planner(llm=self.llm, config=cfg, strategy="flat")

        # Verifier
        self._verifier = Verifier(config=cfg)

        # Context manager
        self._context = ContextManager(config=cfg, budget=self._budget)

        # Adaptive context compactor
        self._compactor = ContextCompactor(cfg.context.compaction)

        # Tools
        self._tools = ToolRegistry(config=cfg)
        await self._tools.setup()  # Discovers and registers all tools

        # Tool learned preferences (None if disabled in config)
        self._tool_prefs: ToolPreferences | None = ToolPreferences(
            store_path=cfg.agent.working_directory + "/.agent/tool_preferences.json",
        )

        # Router (with optional learned preferences)
        self._router = ToolRouter(
            config=cfg,
            registry=self._tools,
            preferences=self._tool_prefs if cfg.tools.router.learned_preferences else None,
        )

        # RAG retriever
        if cfg.rag.enabled:
            self._retriever = Retriever(config=cfg)
            await self._retriever.start()

        # Cross-session memory
        self._memory = MemoryStore(config=cfg)
        await self._memory.start()

        # Recovery
        self._recovery_detector = LoopDetector(config=cfg.recovery)
        self._recovery_strategies = LoopRecovery(llm=self.llm, config=cfg)

        # Auto-detect tool support for local models
        self._tools_enabled = True
        if cfg.llm.provider == "local" and isinstance(self.llm, LocalLLMClient):
            self._tools_enabled = await self.llm.check_tool_support()
            if not self._tools_enabled:
                logger.warning(
                    "Tool calling unsupported by %s — falling back to text-only mode",
                    cfg.llm.model,
                )
                self._tier = RuntimeTier.SMALL

        # Meta-Thinker monitor
        self._meta_thinker = MetaThinker(
            progress_stall_threshold=cfg.recovery.stall_steps,
        )

        # Build initial plan
        self.state.plan = await self._planner.plan(self.task, self._context_summary())

        # Seed conversation with system prompt
        system_msg = self._build_system_message()
        self._messages = [system_msg]

        # Load cross-session memories relevant to this task
        if self._memory:
            # 1. Load AGENTS.md into procedural memory
            self._memory.load_agents_md()

            # 2. Compact old checkpoints (if last compaction >7 days ago)
            self._memory.compact_checkpoints(max_age_days=90)

            # 3. Load relevant episodic + semantic memories
            memories = self._memory.recall_relevant(self.task)
            if memories:
                self._messages.append(
                    Message(
                        role=Role.SYSTEM,
                        content=f"[Project Knowledge]\n{memories}",
                    )
                )

        # Detect initial tier from config profile
        if cfg.context.max_tokens <= 64000:
            self._tier = RuntimeTier.MID
        if cfg.context.max_tokens <= 32000:
            self._tier = RuntimeTier.SMALL
        if cfg.tools.router.strategy == "rules_only":
            self._tier = RuntimeTier.SMALL

        logger.info(
            "Agent initialised: %d subtasks planned, tier=%s",
            len(self.state.plan.subtasks),
            self._tier,
        )

    async def stop(self) -> None:
        """Tear down subsystems and save learnings."""
        if self._memory:
            await self._memory.save_session(self.state)
            await self._memory.close()
        if self._retriever:
            await self._retriever.close()
        if self._tools:
            await self._tools.close()

    async def __aenter__(self) -> AgentCore:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    # ── Main loop ─────────────────────────────────────────────

    async def run(self) -> bool:
        """
        Execute the agent loop until the task is complete or
        max steps / budget is exhausted.

        Returns:
            True if the task was completed successfully.
        """
        assert self._planner is not None, "Call start() first"

        max_steps = self.config.agent.max_steps

        while self.state.step_count < max_steps:
            # 1. Advance to next subtask / phase if needed
            if self.state.plan:
                if self.state.plan.is_hierarchical:
                    # Hierarchical mode: check phase transitions
                    phase = self.state.plan.current_phase
                    if phase is None:
                        # No active phase — advance to next
                        phase = self.state.plan.advance_phase()
                        if phase is None:
                            logger.info("All phases completed")
                            return True
                        logger.info("Starting phase %d: %s", phase.id, phase.name)
                        self._messages.append(
                            Message(
                                role=Role.SYSTEM,
                                content=(
                                    f"Starting phase #{phase.id}: "
                                    f"{phase.name} — {phase.description}"
                                ),
                            )
                        )

                    subtask = None
                    if phase and phase.plan:
                        subtask = phase.plan.current_subtask
                        if subtask is None:
                            subtask = phase.plan.advance()

                    if subtask is None and phase:
                        phase.status = PlanPhase.COMPLETED
                        self.state.plan.current_phase_idx = -1
                        continue
                else:
                    # Flat mode: advance through subtasks
                    if self.state.plan.current_subtask is None:
                        next_sub = self.state.plan.advance()
                        if next_sub is None:
                            logger.info("All subtasks completed")
                            return True
                        logger.info(
                            "Advancing to subtask %d: %s",
                            next_sub.id,
                            next_sub.description,
                        )
                        self._messages.append(
                            Message(
                                role=Role.SYSTEM,
                                content=(
                                    f"Now working on subtask #{next_sub.id}: {next_sub.description}"
                                ),
                            )
                        )

            # 2. Collect any pending concurrent verification result
            #    (overlapped with the previous step's execution)
            if self._pending_verification is not None:
                if self._pending_verification.done():
                    try:
                        verification = self._pending_verification.result()
                        if not verification.passed:
                            logger.info("Concurrent verification: %s", verification.message)
                            content = (
                                f"⚠️ Verification issue: {verification.message}"
                                "\nPlease fix this before proceeding."
                            )
                            self._messages.append(Message(role=Role.SYSTEM, content=content))
                    except Exception as exc:
                        logger.warning("Verification task failed: %s", exc)
                    self._pending_verification = None
                else:
                    # Not done yet — await it (should be rare; verifier is fast)
                    logger.debug("Waiting for pending verification task...")
                    try:
                        verification = await self._pending_verification
                        if not verification.passed:
                            content = (
                                f"⚠️ Verification issue: {verification.message}"
                                "\nPlease fix this before proceeding."
                            )
                            self._messages.append(Message(role=Role.SYSTEM, content=content))
                    except Exception as exc:
                        logger.warning("Verification task failed: %s", exc)
                    self._pending_verification = None

            # 3. Check budget — ACC staged compaction + tier degradation
            if self._budget:
                remaining = self._budget.remaining_fraction()
                if remaining < 0.10 and self._tier == RuntimeTier.LARGE:
                    logger.warning("Degrading tier: LARGE → MID (budget=%.1f%%)", remaining * 100)
                    self._tier = RuntimeTier.MID
                    self._apply_tier()
                if remaining < 0.05 and self._tier == RuntimeTier.MID:
                    logger.warning("Degrading tier: MID → SMALL (budget=%.1f%%)", remaining * 100)
                    self._tier = RuntimeTier.SMALL
                    self._apply_tier()

                # ACC: staged context compaction
                if self._compactor:
                    self._messages = self._compactor.compact(self._messages, remaining)

                # ACC Stage 6: async LLM summarization (cheapest-first means
                # we only reach this when cheaper stages are insufficient)
                if self._compactor and self._compactor.should_run_llm_summarization(remaining):
                    await self._compactor.stage_full_llm(
                        self._messages,
                        llm_summarize=self._llm_summarize,
                    )

            # 4. Execute one step
            step = await self._execute_step()
            if step is None:
                # LLM returned no tool call and no actionable content → done or stuck
                logger.info("Agent returned no action — assuming task complete")
                return True

            self.state.record_step(step)

            # 4. Post-step: update context
            if self._context:
                self._context.record_step(step)

            # 5. Post-step: loop detection
            if self._recovery_detector:
                detection = self._recovery_detector.check(step)
                if detection:
                    logger.warning(
                        "Loop detected: %s (severity=%s)", detection.loop_type, detection.severity
                    )
                    if self._recovery_strategies is None:
                        raise RuntimeError("Recovery strategies not initialised")
                    action = await self._recovery_strategies.recover(detection, self.state)
                    self._apply_recovery(action)
                    self._recovery_attempts += 1
                    if self._recovery_attempts > self.config.recovery.max_recovery_attempts:
                        logger.error("Max recovery attempts reached — stopping")
                        return False
                    continue  # Skip verification, go to next step with intervention

            # Successful step resets recovery counter
            self._recovery_attempts = 0

            # 6. Post-step: Meta-Thinker evaluation
            if self._meta_thinker and self._budget:
                mt_result = self._meta_thinker.evaluate(
                    step, self.state, self._budget.remaining_fraction()
                )
                if mt_result.signal.value in ("interrupt", "fallback"):
                    logger.info(
                        "Meta-Thinker %s: %s",
                        mt_result.signal.value,
                        mt_result.reason,
                    )
                    if mt_result.suggestion:
                        self._messages.append(
                            Message(
                                role=Role.SYSTEM,
                                content=(
                                    f"[Meta-Thinker {mt_result.signal.value}] "
                                    f"{mt_result.suggestion}"
                                ),
                            )
                        )

            # 7. Concurrent verification: kick off background task
            # The result will be consumed at the top of the next loop
            # iteration, overlapping verification with the next LLM call.
            if self._verifier and self.config.agent.verifier_concurrent:
                self._pending_verification = asyncio.create_task(
                    self._verifier.verify(step, self.state)
                )
            elif self._verifier:
                # Synchronous fallback when concurrent mode is off
                verification = await self._verifier.verify(step, self.state)
                if not verification.passed:
                    logger.info("Verification failed: %s", verification.message)
                    content = (
                        f"⚠️ Verification issue: {verification.message}"
                        "\nPlease fix this before proceeding."
                    )
                    self._messages.append(
                        Message(
                            role=Role.SYSTEM,
                            content=content,
                        )
                    )

            # 8. Checkpoint (non-blocking — fast I/O)
            if self.state.step_count % self.config.agent.checkpoint_every_n_steps == 0:
                self._checkpoint()

        logger.warning("Reached max steps (%d)", max_steps)
        return False

    # ── Final response ─────────────────────────────────────────

    @property
    def final_response(self) -> str:
        """
        The content of the last assistant message.

        Returns an empty string if no assistant message has been
        recorded yet.
        """
        for msg in reversed(self._messages):
            if msg.role == Role.ASSISTANT:
                return msg.content
        return ""

    # ── Single step execution ─────────────────────────────────

    async def _execute_step(self) -> Step | None:
        """
        Execute one think → act → observe cycle.

        Returns None if the LLM's response contains no tool call
        and appears to be a final answer.
        """
        assert self._tools is not None
        assert self._router is not None
        assert self._context is not None

        # Get available tools (filtered by router for this context)
        available_tools = self._router.get_available_tools(self.state)
        tool_schemas = [self._tools.schemas[t] for t in available_tools if t in self._tools.schemas]

        # If tool calling is unsupported (auto-detected at startup),
        # skip tool schemas entirely — model generates text only
        if not self._tools_enabled:
            tool_schemas = []

        # Call LLM
        step_number = self.state.step_count + 1
        start_time = time.time()

        # Use streaming for responsiveness
        response_content = ""
        tool_calls: list[ToolCall] = []
        tool_call_accum: dict[str, dict[str, Any]] = {}

        try:
            async for chunk in self.llm.chat_stream(
                messages=self._messages,
                tools=tool_schemas if tool_schemas else None,
            ):
                if chunk.event == StreamEvent.TEXT:
                    response_content += chunk.content
                elif chunk.event == StreamEvent.TOOL_CALL_START:
                    tool_call_accum[chunk.tool_call_id or ""] = {
                        "name": chunk.tool_name or "",
                        "arguments": "",
                    }
                elif chunk.event == StreamEvent.TOOL_CALL_DELTA:
                    cid = chunk.tool_call_id or ""
                    if cid in tool_call_accum:
                        tool_call_accum[cid]["arguments"] += chunk.tool_arguments_delta
                elif chunk.event == StreamEvent.TOOL_CALL_END:
                    cid = chunk.tool_call_id or ""
                    if cid in tool_call_accum:
                        td = tool_call_accum[cid]
                        try:
                            args = json.loads(td["arguments"]) if td["arguments"].strip() else {}
                        except json.JSONDecodeError:
                            args = {"_raw": td["arguments"]}
                        tool_calls.append(ToolCall(id=cid, name=td["name"], arguments=args))
                elif chunk.event == StreamEvent.DONE:
                    break
        except Exception as exc:
            logger.error("LLM call failed: %s", exc)
            return Step(
                step_number=step_number,
                thinking=f"LLM error: {exc}",
                tool_call=None,
                tool_result=ToolResult(
                    tool_call_id="error",
                    tool_name="llm",
                    output=str(exc),
                    success=False,
                    error=str(exc),
                    duration_seconds=time.time() - start_time,
                ),
            )

        # Record assistant message in conversation
        assistant_msg = Message(
            role=Role.ASSISTANT,
            content=response_content,
            tool_calls=tool_calls or None,
        )
        self._messages.append(assistant_msg)

        # If no tool calls, the agent is done or just reasoning
        if not tool_calls:
            # ── Non-tool graceful degradation ──────────────────
            # When the model can't call tools, try to parse a
            # natural-language command from the text response.
            if not self._tools_enabled and response_content.strip():
                step_result = await self._try_text_mode(
                    response_content,
                    step_number,
                    start_time,
                )
                if step_result is not None:
                    return step_result
            return None

        # Execute each tool call
        # For now, execute the first one (multi-tool is a future enhancement)
        call = tool_calls[0]

        # Pre-execution routing rules
        call = self._router.pre_execute(call, self.state)

        # Execute
        result = await self._tools.execute(call)

        # Post-execution routing rules
        result = self._router.post_execute(call, result, self.state)

        # Record tool result in conversation
        self._messages.append(
            Message(
                role=Role.TOOL,
                content=result.output,
                tool_call_id=call.id,
                name=call.name,
            )
        )

        # Record in learned preferences (non-blocking I/O)
        if self._tool_prefs:
            self._tool_prefs.record_result(
                tool_name=call.name,
                success=result.success,
                duration_seconds=result.duration_seconds,
            )

        # Update state tracking
        if call.name in ("edit_file", "write_file"):
            path = call.arguments.get("path", "")
            if path:
                self.state.files_modified.add(path)
        elif call.name in ("read_file", "search_code", "find_symbols", "list_directory"):
            path = call.arguments.get("path", "")
            if path:
                self.state.files_read.add(path)

        return Step(
            step_number=step_number,
            thinking=response_content[:500],  # Truncate reasoning for storage
            tool_call=call,
            tool_result=result,
        )

    # ── Non-tool graceful degradation ───────────────────────

    async def _try_text_mode(
        self,
        response_content: str,
        step_number: int,
        start_time: float,
    ) -> Step | None:
        """
        Try to parse a natural-language command from the LLM's text
        response when tool calling is unavailable.

        Uses a regex-based parser that understands commands like:
          "read src/main.py lines 20-40"
          "edit src/main.py `old text` -> `new text`"
          "search for class AgentCore"
          "run pytest tests/ -v"

        Returns a Step if parsed and executed, None if no command
        was found in the text.
        """
        assert self._tools is not None
        assert self._router is not None

        from coding_agent.tools.text_mode_parser import (
            extract_command_from_response,
            parse_text_command,
        )

        cmd_text = extract_command_from_response(response_content)
        if not cmd_text:
            return None

        call = parse_text_command(cmd_text)
        if call is None:
            return None

        logger.info("Text-mode parsed: %s(%s)", call.name, call.arguments)

        # Pre-execution routing (clamp ranges, set defaults)
        call = self._router.pre_execute(call, self.state)

        # Execute
        result = await self._tools.execute(call)

        # Post-execution routing (truncate output, log hints)
        result = self._router.post_execute(call, result, self.state)

        # Record tool result in conversation
        self._messages.append(
            Message(
                role=Role.TOOL,
                content=result.output,
                tool_call_id=call.id,
                name=call.name,
            )
        )

        # Record in learned preferences
        if self._tool_prefs:
            self._tool_prefs.record_result(
                tool_name=call.name,
                success=result.success,
                duration_seconds=result.duration_seconds,
            )

        # Update state tracking
        if call.name in ("edit_file", "write_file"):
            path = call.arguments.get("path", "")
            if path:
                self.state.files_modified.add(path)
        elif call.name in ("read_file", "search_code", "find_symbols", "list_directory"):
            path = call.arguments.get("path", "")
            if path:
                self.state.files_read.add(path)

        return Step(
            step_number=step_number,
            thinking=response_content[:500],
            tool_call=call,
            tool_result=result,
        )

    # ── Tier application ────────────────────────────────────
    # ── System message builder ────────────────────────────────

    def _build_system_message(self) -> Message:
        """Build the system prompt with current task and subtask."""
        task_desc = self.task
        subtask_section = ""

        if self.state.plan and self.state.plan.current_subtask:
            st = self.state.plan.current_subtask
            subtask_section = _SUBTASK_SECTION.format(
                subtask_id=st.id,
                total=len(self.state.plan.subtasks),
                subtask_description=st.description,
                files=", ".join(st.files) if st.files else "unknown",
            )

        content = _SYSTEM_PROMPT_BASE.format(
            task_description=task_desc,
            subtask_section=subtask_section,
        )

        return Message(role=Role.SYSTEM, content=content)

    # ── Tier management ───────────────────────────────────────

    def _apply_tier(self) -> None:
        """Adjust subsystems when the runtime tier changes."""
        tier = self._tier
        logger.info("Applying tier: %s", tier)

        # Adjust budget if needed
        if self._budget and tier == RuntimeTier.SMALL:
            self._budget.max_fraction_per_step = 0.05

        # Inject a system message so the LLM knows resource constraints
        if self._budget:
            frac = self._budget.remaining_fraction()
            msg = f"[Resource constraint: tier={tier}, budget={frac:.0%} remaining]"
            self._messages.append(Message(role=Role.SYSTEM, content=msg))

    # ── ACC Stage 6 LLM summarizer ────────────────────────────

    async def _llm_summarize(self, conversation_text: str) -> str:
        """
        Lightweight LLM call to compress mid-conversation history.

        Uses a short prompt with two-phase CoT: the LLM reasons
        about what to keep, then outputs a structured summary.
        The CoT is consumed (not kept in context).
        """
        prompt = (
            "Compress this conversation for a coding agent.\n"
            "First, reason step-by-step about what to keep.\n"
            "Then output a structured summary with:\n"
            "  - GOAL: What was the task?\n"
            "  - PROGRESS: What has been done?\n"
            "  - FINDINGS: What was discovered?\n"
            "  - NEXT: What remains?\n\n"
            f"{conversation_text}"
        )
        try:
            response = await self.llm.chat(
                messages=[Message(role=Role.USER, content=prompt)],
                temperature=0.2,
                max_tokens=1024,
            )
            return response.content
        except Exception as exc:
            logger.warning("LLM summarization failed: %s", exc)
            return "[summarization unavailable]"

    # ── Context helpers ───────────────────────────────────────

    def _context_summary(self) -> str:
        """
        Produce a short summary of the current project context
        for the planner.  Uses RAG if available.
        """
        if self._retriever:
            # Get a high-level overview from the RAG index
            return self._retriever.project_overview()
        # Fallback: just list the directory
        return f"Working directory: {self.config.agent.working_directory}"

    async def _emergency_compression(self) -> None:
        """
        Aggressively compress the context window to free up budget.

        Strategies (in order):
          1. Summarise older working-memory entries into episodic
          2. Truncate long tool outputs
          3. Remove semantic memory zone
          4. Drop oldest messages from conversation history
        """
        assert self._context is not None
        assert self._budget is not None

        logger.warning(
            "Emergency compression triggered at %.1f%% remaining",
            self._budget.remaining_fraction() * 100,
        )

        # Strategy 1: context manager compression
        self._context.emergency_compress()

        # Strategy 2: truncate long tool outputs in message history
        for msg in self._messages:
            if msg.role == Role.TOOL and len(msg.content) > 1000:
                lines = msg.content.split("\n")
                if len(lines) > 30:
                    msg.content = (
                        "\n".join(lines[:10])
                        + "\n... [truncated for space] ...\n"
                        + "\n".join(lines[-10:])
                    )

        # Strategy 3: drop oldest assistant+tool pairs (keep first 2 and last N)
        if len(self._messages) > 20:
            # Keep system messages and the most recent turns
            system_msgs = [m for m in self._messages if m.role == Role.SYSTEM]
            recent = self._messages[-10:]
            self._messages = (
                system_msgs
                + [
                    Message(
                        role=Role.SYSTEM,
                        content="[Earlier conversation steps omitted to save space]",
                    )
                ]
                + recent
            )

    # ── Recovery ──────────────────────────────────────────────

    def _apply_recovery(self, action: RecoveryAction) -> None:
        """Inject a recovery intervention into the conversation."""
        if action.inject_message:
            self._messages.append(
                Message(
                    role=Role.SYSTEM,
                    content=action.inject_message,
                )
            )

        if action.reset_working_memory and self._context:
            self._context.reset_working()

        if action.force_user_intervention:
            self._messages.append(
                Message(
                    role=Role.SYSTEM,
                    content=(
                        "The agent is stuck. Consider providing additional guidance "
                        "or simplifying the task."
                    ),
                )
            )

    # ── Checkpoint ────────────────────────────────────────────

    _session_id: str = ""

    def _checkpoint(self) -> None:
        """Save a lightweight checkpoint of the agent state to disk."""
        if not self._memory:
            logger.info("Checkpoint skipped (no memory store): step %d", self.state.step_count)
            return
        if not self._session_id:
            self._session_id = f"session_{int(time.time())}_{id(self)}"
        self._memory.checkpoint_save(self.state, session_id=self._session_id)
