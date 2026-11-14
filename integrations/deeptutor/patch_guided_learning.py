"""Install the server-owned teaching boundaries in the pinned tutor image."""
from pathlib import Path
import sys

from patch_kaoyan_questions import transform


def apply(root):
    transform(root / 'runtime/request_contracts.py', [
        ('class ChatRequestConfig(EmptyConfig):\n    pass',
         'class ChatRequestConfig(EmptyConfig):\n    zx_feedback_only: bool | None = None'),
        ('class MasteryPathRequestConfig(EmptyConfig):\n    pass',
         '''class MasteryPathRequestConfig(EmptyConfig):
    zx_grade_only: bool | None = None
    zx_objective: str | None = None
    zx_teach: bool | None = None'''),
    ])
    transform(root / 'services/session/turns/executor.py', [
        ('            history_result = await builder.build(\n',
         '''            if request_config.get("zx_grade_only") and payload.get("mastery_answer"):
                from deeptutor.services.session.context_builder import ContextBuildResult

                history_result = ContextBuildResult([], "", "", [], 0, 0)
            else:
                history_result = await builder.build(\n'''),
        ('''                session_id=session_id,
                llm_config=llm_config,
                language=payload.get("language", "en"),
                on_event=_emit_context_event,
                leaf_message_id=branch_parent_id,
            )''',
         '''                    session_id=session_id,
                    llm_config=llm_config,
                    language=payload.get("language", "en"),
                    on_event=_emit_context_event,
                    leaf_message_id=branch_parent_id,
                )'''),
        ('            async for event in self.turn_engine.execute(context):',
         '''            async def guided_events():
                if request_config.get("zx_grade_only") and payload.get("mastery_answer"):
                    grade = mastery_card_grade or {}
                    verdict = grade.get("result") or {}
                    rows = verdict.get("results") or verdict.get("items") or [verdict]
                    feedback = [
                        str(row.get("feedback") or row.get("explanation") or "")
                        for row in rows if isinstance(row, dict)
                    ]
                    yield StreamEvent(
                        type=StreamEventType.CONTENT, source="mastery",
                        content="\\n".join(filter(None, feedback)) or "本次作答未产生可显示的讲评，请查看题卡状态。",
                    )
                else:
                    async for item in self.turn_engine.execute(context):
                        yield item

            async for event in guided_events():'''),
    ])
    transform(root / 'agents/loop/pipeline.py', [
        ('        # Capabilities may bind records to text the turn has actually published.',
         '''        if context.config_overrides.get("zx_objective") or context.config_overrides.get("zx_feedback_only"):
            allowed = set(self._compose_enabled_tools(context))
            if context.config_overrides.get("zx_feedback_only"):
                allowed &= {"rag", "read_source", "kb_files"}
            tool_calls = [call if call.get("name") in allowed else {**call, "name": "zx_tool_not_available"}
                          for call in tool_calls]
        # Capabilities may bind records to text the turn has actually published.'''),
        ('        return list(dict.fromkeys(composed))',
         '''        if context.config_overrides.get("zx_feedback_only"):
            composed = [name for name in composed if name in {"rag", "read_source", "kb_files"}]
        return list(dict.fromkeys(composed))'''),
    ])
    transform(root / 'capabilities/mastery/pipeline.py', [
        ('        return [name for name in super()._compose_enabled_tools(context) if name not in deferred]',
         '''        names = [name for name in super()._compose_enabled_tools(context) if name not in deferred]
        if context.config_overrides.get("zx_objective"):
            permitted = {"rag", "read_source", "kb_files", "mastery_status",
                         "mastery_prepare_lesson", "mastery_note_explained", "mastery_quiz"}
            return [name for name in names if name in permitted]
        return names'''),
    ])
    transform(root / 'capabilities/mastery/loop.py', [
        ('                updated["_end_turn_on_card"] = _card_end_marker(context)',
         '''                updated["_end_turn_on_card"] = _card_end_marker(context)
                updated["_zx_objective"] = context.config_overrides.get("zx_objective")
                updated["_zx_require_explanation"] = bool(context.config_overrides.get("zx_teach"))'''),
    ])
    transform(root / 'capabilities/mastery/tools.py', [
        ('        pending_action = kwargs.get("pending_action", "retain")\n        resume_id',
         '''        objective = kwargs.get("_zx_objective")
        if objective and (
            kwargs.get("knowledge_point_id") != objective or kwargs.get("questions")
            or kwargs.get("pending_action", "retain") != "retain"
        ):
            return ToolResult(content="Register one question for the assigned objective.", success=False)
        if objective and kwargs.get("_zx_require_explanation"):
            exposure = progress.explained_objectives.get(objective) or {}
            if exposure.get("turn_id") != _resolve_turn_id(kwargs):
                return ToolResult(content="Deliver and record the explanation before posing the check.", success=False)
        pending_action = kwargs.get("pending_action", "retain")
        resume_id'''),
    ])
    transform(root / 'services/session/sqlite_store.py', [
        ('    def _get_messages_sync(self, session_id: str) -> list[dict[str, Any]]:',
         '''    async def zx_recent_text(self, session_id: str) -> list[dict[str, Any]]:
        def fetch():
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT role, content, created_at FROM messages WHERE session_id = ? "
                    "AND role IN ('user', 'assistant') ORDER BY id DESC LIMIT 100", (session_id,),
                ).fetchall()
                return [dict(row) for row in reversed(rows)]
        return await self._run(fetch)

    def _get_messages_sync(self, session_id: str) -> list[dict[str, Any]]:'''),
    ])


if __name__ == '__main__':
    apply(Path(sys.argv[1]))
