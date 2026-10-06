import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent import build_main_prompt, close_agent, generate_answer, generate_merge, initialize_agent, run_branch
from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .models import (
    AnswerVersion,
    AnswerVersionSource,
    Branch,
    BranchMessage,
    BranchSelection,
    Conversation,
    MergeDraft,
    MessageContextSource,
    Message,
    Passage,
    new_id,
    utcnow,
)
from .schemas import AskRequest, BranchRequest, ConfirmMergeRequest, ContinueRequest, MergeRequest

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("inlinegraph.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    initialize_agent()
    seed_demo_if_empty()
    yield
    close_agent()


app = FastAPI(title="InlineGraph AI API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


def _split_passages(content: str) -> list[tuple[str, int, int]]:
    parts = []
    for match in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|$)", content, re.S):
        text = match.group(0).strip()
        if text:
            start = content.find(text, match.start(), match.end())
            parts.append((text, start, start + len(text)))
    return parts


def _add_message(db: Session, conversation_id: str, role: str, content: str, answer_version_id: str | None = None) -> Message:
    message = Message(
        id=new_id(), conversation_id=conversation_id, role=role, content=content, answer_version_id=answer_version_id
    )
    db.add(message)
    db.flush()
    if role == "assistant":
        for ordinal, (text, start, end) in enumerate(_split_passages(content)):
            db.add(Passage(id=new_id(), message_id=message.id, ordinal=ordinal, content=text, start_offset=start, end_offset=end))
    return message


def seed_demo_if_empty() -> None:
    with SessionLocal.begin() as db:
        if db.scalar(select(Conversation.id).limit(1)):
            return
        conversation = Conversation(id=new_id(), title="Urban heat and tree cover")
        db.add(conversation)
        db.flush()
        question = "What are the main causes of urban heat?"
        answer = (
            "Dark surfaces absorb more heat than lighter materials, and dense buildings can trap that warmth between streets. "
            "These effects are strongest where shade and vegetation are limited.\n\n"
            "Tree cover can reduce heat by shading streets and buildings and by releasing water vapor through evapotranspiration. "
            "Its impact depends on canopy size, local climate, and where trees are planted.\n\n"
            "Urban heat also reflects broader conditions, including waste heat from vehicles and buildings, limited airflow, "
            "and the amount of green space. These factors interact, so solutions usually combine shade, reflective materials, "
            "building design, and cooler public spaces."
        )
        user_message = _add_message(db, conversation.id, "user", question)
        version = AnswerVersion(id=new_id(), conversation_id=conversation.id, version_number=1, content=answer)
        db.add(version)
        db.flush()
        _add_message(db, conversation.id, "assistant", answer, version.id)
        conversation.updated_at = utcnow()
        logger.info("Seeded local demo conversation %s", conversation.id)


def _latest_version(db: Session, conversation_id: str) -> AnswerVersion | None:
    return db.scalar(
        select(AnswerVersion)
        .where(AnswerVersion.conversation_id == conversation_id)
        .order_by(AnswerVersion.version_number.desc())
        .limit(1)
    )


def _serialize_conversation(db: Session, conversation: Conversation) -> dict:
    messages = db.scalars(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at, Message.id)
    ).all()
    serialized_messages = []
    for message in messages:
        passage_rows = db.scalars(select(Passage).where(Passage.message_id == message.id).order_by(Passage.ordinal)).all()
        serialized_messages.append(
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "answer_version_id": message.answer_version_id,
                "created_at": message.created_at.isoformat(),
                "passages": [
                    {"id": p.id, "ordinal": p.ordinal, "content": p.content, "start_offset": p.start_offset, "end_offset": p.end_offset}
                    for p in passage_rows
                ],
            }
        )
    branches = db.scalars(
        select(Branch).where(Branch.conversation_id == conversation.id).order_by(Branch.created_at)
    ).all()
    serialized_branches = []
    for branch in branches:
        passage = db.get(Passage, branch.source_passage_id)
        rows = db.scalars(
            select(BranchMessage).where(BranchMessage.branch_id == branch.id).order_by(BranchMessage.created_at, BranchMessage.id)
        ).all()
        selection_rows = db.scalars(
            select(BranchSelection)
            .where(BranchSelection.branch_id == branch.id)
            .order_by(BranchSelection.ordinal)
        ).all()
        serialized_branches.append(
            {
                "id": branch.id,
                "conversation_id": branch.conversation_id,
                "source_passage_id": branch.source_passage_id,
                "source_answer_version_id": branch.source_answer_version_id,
                "parent_branch_id": branch.parent_branch_id,
                "action_type": branch.action_type,
                "user_instruction": branch.user_instruction,
                "status": branch.status,
                "accepted": branch.accepted,
                "reviewer_note": branch.reviewer_note,
                "source_passage": passage.content if passage else "",
                "selections": [
                    {
                        "text": item.selected_text,
                        "source_passage_ids": json.loads(item.source_passage_ids),
                    }
                    for item in selection_rows
                ],
                "created_at": branch.created_at.isoformat(),
                "messages": [
                    {"id": row.id, "role": row.role, "content": row.content, "created_at": row.created_at.isoformat()}
                    for row in rows
                ],
            }
        )
    versions = db.scalars(
        select(AnswerVersion).where(AnswerVersion.conversation_id == conversation.id).order_by(AnswerVersion.version_number)
    ).all()
    context_sources = db.scalars(
        select(MessageContextSource)
        .join(Message, MessageContextSource.target_message_id == Message.id)
        .where(Message.conversation_id == conversation.id)
        .order_by(MessageContextSource.id)
    ).all()
    context_source_payload = [
        {
            "target_message_id": item.target_message_id,
            "source_branch_id": item.source_branch_id,
            "source_branch_message_ids": json.loads(item.source_branch_message_ids),
            "source_status": item.source_status,
            "source_accepted": item.source_accepted,
            "inferred": False,
        }
        for item in context_sources
    ]
    recorded_targets = {item["target_message_id"] for item in context_source_payload}

    def timestamp(value: datetime) -> float:
        return value.replace(tzinfo=timezone.utc).timestamp() if value.tzinfo is None else value.timestamp()

    # Before context-use links were persisted, main prompts included every branch
    # created before the question. Reconstruct those historical graph links.
    for question in (message for message in messages if message.role == "user" and message.id not in recorded_targets):
        for branch in branches:
            if timestamp(branch.created_at) > timestamp(question.created_at):
                continue
            prior_branch_message_ids = [
                row.id
                for row in db.scalars(
                    select(BranchMessage)
                    .where(BranchMessage.branch_id == branch.id)
                    .order_by(BranchMessage.created_at, BranchMessage.id)
                ).all()
                if timestamp(row.created_at) <= timestamp(question.created_at)
            ]
            context_source_payload.append(
                {
                    "target_message_id": question.id,
                    "source_branch_id": branch.id,
                    "source_branch_message_ids": prior_branch_message_ids,
                    "source_status": branch.status,
                    "source_accepted": None,
                    "inferred": True,
                }
            )
    latest = versions[-1] if versions else None
    return {
        "id": conversation.id,
        "title": conversation.title,
        "current_answer_version_id": latest.id if latest else None,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
        "messages": serialized_messages,
        "branches": serialized_branches,
        "context_sources": context_source_payload,
        "versions": [
            {"id": v.id, "version_number": v.version_number, "content": v.content, "created_at": v.created_at.isoformat()}
            for v in versions
        ],
    }


def _get_conversation(db: Session, conversation_id: str) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _context_for_branch(db: Session, branch: Branch) -> tuple[str, str, list[dict[str, str]]]:
    source = db.get(Passage, branch.source_passage_id)
    source_version = db.get(AnswerVersion, branch.source_answer_version_id)
    if source is None or source_version is None:
        raise HTTPException(status_code=409, detail="The branch source is no longer available")
    source_message = db.get(Message, source.message_id)
    user_question = ""
    if source_message:
        ordered_messages = db.scalars(
            select(Message)
            .where(Message.conversation_id == branch.conversation_id)
            .order_by(Message.created_at, Message.id)
        ).all()
        source_index = next((i for i, item in enumerate(ordered_messages) if item.id == source_message.id), len(ordered_messages))
        user_question = next(
            (item.content for item in reversed(ordered_messages[:source_index]) if item.role == "user"),
            "",
        )
    history = []
    if branch.parent_branch_id:
        parent_rows = db.scalars(
            select(BranchMessage).where(BranchMessage.branch_id == branch.parent_branch_id).order_by(BranchMessage.created_at)
        ).all()
        history.extend({"role": row.role, "content": row.content} for row in parent_rows)
    rows = db.scalars(
        select(BranchMessage).where(BranchMessage.branch_id == branch.id).order_by(BranchMessage.created_at)
    ).all()
    history.extend({"role": row.role, "content": row.content} for row in rows)
    return user_question, source_version.content, history


def _conversation_context(db: Session, conversation_id: str, exclude_branch_id: str | None = None) -> str:
    messages = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
    ).all()
    lines = ["Main conversation so far:"]
    for message in messages:
        speaker = "User" if message.role == "user" else "Assistant"
        lines.append(f"{speaker}: {message.content}")

    branches = db.scalars(
        select(Branch)
        .where(Branch.conversation_id == conversation_id)
        .order_by(Branch.created_at, Branch.id)
    ).all()
    prior_branches = [branch for branch in branches if branch.id != exclude_branch_id]
    accepted_branches = [branch for branch in prior_branches if branch.accepted is True]
    other_branches = [branch for branch in prior_branches if branch.accepted is not True]
    groups = (
        (
            accepted_branches,
            "\nUser-accepted branch answers (carry these forward as approved conversation context; "
            "use the accepted answer when a later question relates to it):",
        ),
        (other_branches, "\nOther earlier passage explorations (retain as background, with their review status):"),
    )
    for group, heading in groups:
        if group:
            lines.append(heading)
        for branch in group:
            selections = db.scalars(
                select(BranchSelection)
                .where(BranchSelection.branch_id == branch.id)
                .order_by(BranchSelection.ordinal)
            ).all()
            rows = db.scalars(
                select(BranchMessage)
                .where(BranchMessage.branch_id == branch.id)
                .order_by(BranchMessage.created_at, BranchMessage.id)
            ).all()
            source_ids = [branch.source_passage_id]
            for selection in selections:
                try:
                    source_ids.extend(json.loads(selection.source_passage_ids))
                except (TypeError, json.JSONDecodeError):
                    source_ids.append(selection.source_passage_id)
            sources = []
            for source_id in dict.fromkeys(source_ids):
                source = db.get(Passage, source_id)
                if source:
                    sources.append(source)
            decision_label = "accepted" if branch.accepted is True else branch.status
            lines.append(f"\nBranch node {branch.id} ({decision_label}):")
            if selections:
                lines.extend(f"Selected text: {item.selected_text}" for item in selections)
            elif sources:
                lines.append(f"Selected text: {sources[0].content}")
            lines.extend(f"Source paragraph: {source.content}" for source in sources)
            if branch.accepted is True:
                lines.append("User-approved branch result; preserve relevant corrections, choices, and constraints in later answers.")
            lines.extend(f"{'User' if row.role == 'user' else 'Assistant'}: {row.content}" for row in rows)
    return "\n".join(lines)


@app.get("/api/health")
def health():
    try:
        mock = settings.use_mock_model
    except RuntimeError:
        mock = False
    return {"status": "ok", "provider": "mock" if mock else "groq", "model": settings.groq_model}


@app.get("/api/demo")
def get_demo(db: Session = Depends(get_db)):
    conversations = db.scalars(select(Conversation)).all()
    activity = {
        item.id: (item.updated_at.replace(tzinfo=timezone.utc).timestamp() if item.updated_at.tzinfo is None else item.updated_at.timestamp())
        for item in conversations
    }
    for branch in db.scalars(select(Branch)).all():
        branch_time = branch.updated_at.replace(tzinfo=timezone.utc).timestamp() if branch.updated_at.tzinfo is None else branch.updated_at.timestamp()
        activity[branch.conversation_id] = max(activity.get(branch.conversation_id, 0), branch_time)
    conversation = max(conversations, key=lambda item: (activity[item.id], item.created_at)) if conversations else None
    if conversation is None:
        raise HTTPException(status_code=404, detail="No conversation is available")
    mode = "mock" if settings.use_mock_model else "groq"
    return {"provider": mode, "model": settings.groq_model, "conversation": _serialize_conversation(db, conversation)}


@app.post("/api/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(db: Session = Depends(get_db)):
    conversation = Conversation(title="New conversation")
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return _serialize_conversation(db, conversation)


@app.post("/api/conversations/{conversation_id}/messages")
def ask_question(conversation_id: str, request: AskRequest, db: Session = Depends(get_db)):
    conversation = _get_conversation(db, conversation_id)
    prior_context = _conversation_context(db, conversation.id)
    prompt = build_main_prompt(request.question, prior_context)
    context_branches = db.scalars(
        select(Branch)
        .where(Branch.conversation_id == conversation.id)
        .order_by(Branch.created_at, Branch.id)
    ).all()
    branch_context_log = []
    with db.begin_nested():
        question_message = _add_message(db, conversation.id, "user", request.question.strip())
        for branch in context_branches:
            branch_message_ids = [
                row.id
                for row in db.scalars(
                    select(BranchMessage)
                    .where(BranchMessage.branch_id == branch.id)
                    .order_by(BranchMessage.created_at, BranchMessage.id)
                ).all()
            ]
            db.add(
                MessageContextSource(
                    target_message_id=question_message.id,
                    source_branch_id=branch.id,
                    source_branch_message_ids=json.dumps(branch_message_ids),
                    source_status=branch.status,
                    source_accepted=branch.accepted,
                )
            )
            branch_context_log.append(
                {
                    "branch_id": branch.id,
                    "status": branch.status,
                    "accepted": branch.accepted,
                    "branch_message_ids": branch_message_ids,
                }
            )
        answer = generate_answer(request.question, prior_context, prompt=prompt)
        latest = _latest_version(db, conversation.id)
        version = AnswerVersion(
            conversation_id=conversation.id,
            version_number=(latest.version_number + 1 if latest else 1),
            content=answer,
            created_by="assistant",
        )
        db.add(version)
        db.flush()
        _add_message(db, conversation.id, "assistant", answer, version.id)
        if conversation.title == "New conversation":
            conversation.title = request.question.strip()[:72]
        conversation.updated_at = utcnow()
    db.commit()
    serialized = _serialize_conversation(db, conversation)
    if request.debug:
        serialized["debug_trace"] = {
            "provider": "mock" if settings.use_mock_model else "groq",
            "model": settings.groq_model,
            "request_body": {"question": request.question.strip()},
            "model_calls": [
                {
                    "purpose": "main chat answer",
                    "sent_to_provider": not settings.use_mock_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "parameters": {"temperature": 0.25, "max_tokens": 768},
                    "response": answer,
                }
            ],
            "context_sources": branch_context_log,
        }
    return serialized


@app.post("/api/conversations/{conversation_id}/branches", status_code=status.HTTP_201_CREATED)
def create_branch(conversation_id: str, request: BranchRequest, db: Session = Depends(get_db)):
    conversation = _get_conversation(db, conversation_id)
    passage = db.get(Passage, request.source_passage_id)
    version = db.get(AnswerVersion, request.source_answer_version_id)
    if passage is None or version is None:
        raise HTTPException(status_code=404, detail="Source passage or answer version not found")
    source_message = db.get(Message, passage.message_id)
    if source_message is None or source_message.conversation_id != conversation.id or version.conversation_id != conversation.id:
        raise HTTPException(status_code=422, detail="Source passage and answer version must belong to this conversation")
    if source_message.answer_version_id != version.id:
        raise HTTPException(status_code=422, detail="The selected passage must belong to the selected answer version")

    selection_inputs = request.selections or [{"text": passage.content, "source_passage_ids": [passage.id]}]
    validated_selections: list[tuple[str, list[str]]] = []
    source_passages: dict[str, Passage] = {}
    total_selection_chars = 0
    for item in selection_inputs:
        selected_text = item.text.strip() if hasattr(item, "text") else str(item["text"]).strip()
        passage_ids = item.source_passage_ids if hasattr(item, "source_passage_ids") else item["source_passage_ids"]
        if not selected_text:
            raise HTTPException(status_code=422, detail="Selected text cannot be empty")
        total_selection_chars += len(selected_text)
        normalized_ids = list(dict.fromkeys(passage_ids))
        for selected_id in normalized_ids:
            selected_passage = db.get(Passage, selected_id)
            selected_message = db.get(Message, selected_passage.message_id) if selected_passage else None
            if (
                selected_passage is None
                or selected_message is None
                or selected_message.conversation_id != conversation.id
                or selected_message.answer_version_id != version.id
            ):
                raise HTTPException(status_code=422, detail="Every selected text fragment must come from this answer")
            source_passages[selected_id] = selected_passage
        if not normalized_ids:
            raise HTTPException(status_code=422, detail="Each selection must reference at least one source passage")
        validated_selections.append((selected_text, normalized_ids))
    if total_selection_chars > 24000:
        raise HTTPException(status_code=422, detail="Combined selections must be 24,000 characters or fewer")

    primary_passage_id = validated_selections[0][1][0]
    source_context = "\n\n".join(item.content for item in source_passages.values())
    selected_text = "\n\n".join(f"Selection {index}: {text}" for index, (text, _) in enumerate(validated_selections, start=1))
    branch = Branch(
        conversation_id=conversation.id,
        source_passage_id=primary_passage_id,
        source_answer_version_id=version.id,
        action_type=request.action_type,
        user_instruction=request.user_instruction.strip(),
        status="running",
    )
    db.add(branch)
    db.flush()
    db.add(BranchMessage(branch_id=branch.id, role="user", content=request.user_instruction.strip()))
    for ordinal, (fragment, passage_ids) in enumerate(validated_selections):
        db.add(
            BranchSelection(
                branch_id=branch.id,
                ordinal=ordinal,
                source_passage_id=passage_ids[0],
                source_passage_ids=json.dumps(passage_ids),
                selected_text=fragment,
            )
        )
    db.flush()
    prior = _context_for_branch(db, branch)
    branch_history = prior[2][:-1] if prior[2] and prior[2][-1]["role"] == "user" else prior[2]
    conversation_context = _conversation_context(db, conversation.id, exclude_branch_id=branch.id)
    try:
        result = run_branch(
            {
                "action": "ask",
                "instruction": request.user_instruction.strip(),
                "source_passage": source_context,
                "selected_text": selected_text,
                "branch_history": branch_history,
                "conversation_context": conversation_context,
                "revision_count": 0,
                "use_mock": settings.use_mock_model,
            },
            branch.id,
        )
        response = result.get("response", "")
        branch.reviewer_note = result.get("review", "")
        branch.status = "ready_for_review"
        db.add(BranchMessage(branch_id=branch.id, role="assistant", content=response))
        conversation.updated_at = utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Branch workflow failed")
        raise HTTPException(status_code=502, detail=f"Branch generation failed. Check the API key, model access, or retry. ({type(exc).__name__})") from exc
    serialized = _serialize_conversation(db, conversation)
    if request.debug:
        serialized["debug_trace"] = {
            "provider": "mock" if settings.use_mock_model else "groq",
            "model": settings.groq_model,
            "request_body": request.model_dump(exclude={"debug"}),
            "model_calls": result.get("model_call_log", []),
        }
    return serialized


@app.post("/api/branches/{branch_id}/messages")
def continue_branch(branch_id: str, request: ContinueRequest, db: Session = Depends(get_db)):
    branch = db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    conversation = _get_conversation(db, branch.conversation_id)
    if branch.status == "failed":
        raise HTTPException(status_code=409, detail="Failed branch cannot be continued")
    # New content invalidates the previous acceptance; the updated branch must be reviewed again.
    branch.accepted = None
    db.add(BranchMessage(branch_id=branch.id, role="user", content=request.message.strip()))
    db.flush()
    history = _context_for_branch(db, branch)[2]
    if history and history[-1]["role"] == "user" and history[-1]["content"] == request.message.strip():
        history = history[:-1]
    selection_rows = db.scalars(
        select(BranchSelection)
        .where(BranchSelection.branch_id == branch.id)
        .order_by(BranchSelection.ordinal)
    ).all()
    source = db.get(Passage, branch.source_passage_id)
    selected_text = "\n\n".join(
        f"Selection {index}: {item.selected_text}"
        for index, item in enumerate(selection_rows, start=1)
    ) or (source.content if source else "")
    source_context = "\n\n".join(
        passage.content
        for passage_id in dict.fromkeys(
            passage_id
            for item in selection_rows
            for passage_id in json.loads(item.source_passage_ids)
        )
        if (passage := db.get(Passage, passage_id)) is not None
    ) or (source.content if source else "")
    conversation_context = _conversation_context(db, conversation.id, exclude_branch_id=branch.id)
    try:
        result = run_branch(
            {
                "action": "ask",
                "instruction": request.message.strip(),
                "source_passage": source_context,
                "selected_text": selected_text,
                "branch_history": history,
                "conversation_context": conversation_context,
                "revision_count": 0,
                "use_mock": settings.use_mock_model,
            },
            branch.id,
        )
        db.add(BranchMessage(branch_id=branch.id, role="assistant", content=result.get("response", "")))
        branch.reviewer_note = result.get("review", "")
        branch.status = "ready_for_review"
        branch.updated_at = utcnow()
        conversation.updated_at = utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Branch continuation failed")
        raise HTTPException(status_code=502, detail=f"Branch continuation failed. ({type(exc).__name__})") from exc
    serialized = _serialize_conversation(db, conversation)
    if request.debug:
        serialized["debug_trace"] = {
            "provider": "mock" if settings.use_mock_model else "groq",
            "model": settings.groq_model,
            "request_body": request.model_dump(exclude={"debug"}),
            "model_calls": result.get("model_call_log", []),
        }
    return serialized


@app.patch("/api/branches/{branch_id}/status")
def update_branch_status(branch_id: str, decision: str, db: Session = Depends(get_db)):
    branch = db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    if decision not in {"accept", "reject"}:
        raise HTTPException(status_code=422, detail="Decision must be accept or reject")
    branch.accepted = decision == "accept"
    branch.status = "accepted" if decision == "accept" else "rejected"
    branch.updated_at = utcnow()
    conversation = _get_conversation(db, branch.conversation_id)
    conversation.updated_at = utcnow()
    db.commit()
    return _serialize_conversation(db, conversation)


@app.post("/api/conversations/{conversation_id}/merges")
def create_merge_draft(conversation_id: str, request: MergeRequest, db: Session = Depends(get_db)):
    conversation = _get_conversation(db, conversation_id)
    latest = _latest_version(db, conversation_id)
    if latest is None:
        raise HTTPException(status_code=409, detail="There is no answer to revise")
    branches = [db.get(Branch, branch_id) for branch_id in request.branch_ids]
    if any(branch is None or branch.conversation_id != conversation_id for branch in branches):
        raise HTTPException(status_code=422, detail="Every selected branch must belong to this conversation")
    if any(branch.status != "accepted" for branch in branches if branch):
        raise HTTPException(status_code=409, detail="Only accepted branches can be merged")
    selected = []
    for branch in branches:
        passage = db.get(Passage, branch.source_passage_id)
        selection_rows = db.scalars(
            select(BranchSelection)
            .where(BranchSelection.branch_id == branch.id)
            .order_by(BranchSelection.ordinal)
        ).all()
        answer_message = db.scalar(
            select(BranchMessage).where(BranchMessage.branch_id == branch.id, BranchMessage.role == "assistant").order_by(BranchMessage.created_at.desc()).limit(1)
        )
        selected.append({
            "passage": passage.content if passage else "",
            "selected_text": "\n\n".join(item.selected_text for item in selection_rows),
            "response": answer_message.content if answer_message else "",
        })
    try:
        proposed = generate_merge(latest.content, selected)
    except Exception as exc:
        logger.exception("Merge draft generation failed")
        raise HTTPException(status_code=502, detail=f"Merge draft generation failed. ({type(exc).__name__})") from exc
    draft = MergeDraft(
        conversation_id=conversation.id,
        base_answer_version_id=latest.id,
        branch_ids=json.dumps(request.branch_ids),
        proposed_content=proposed,
    )
    db.add(draft)
    db.commit()
    return {"id": draft.id, "content": draft.proposed_content, "base_answer_version_id": draft.base_answer_version_id}


@app.post("/api/conversations/{conversation_id}/merges/{merge_id}/confirm")
def confirm_merge(conversation_id: str, merge_id: str, request: ConfirmMergeRequest, db: Session = Depends(get_db)):
    conversation = _get_conversation(db, conversation_id)
    draft = db.get(MergeDraft, merge_id)
    if draft is None or draft.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="Merge draft not found")
    if draft.confirmed_at is not None:
        raise HTTPException(status_code=409, detail="Merge has already been confirmed")
    base_version = db.get(AnswerVersion, draft.base_answer_version_id)
    if base_version is None:
        raise HTTPException(status_code=409, detail="The base answer version no longer exists")
    latest = _latest_version(db, conversation_id)
    if latest and latest.id != base_version.id:
        raise HTTPException(status_code=409, detail="The main answer changed after this draft. Create a fresh merge draft.")
    branch_ids = json.loads(draft.branch_ids)
    branches = [db.get(Branch, branch_id) for branch_id in branch_ids]
    if any(branch is None or branch.status != "accepted" for branch in branches):
        raise HTTPException(status_code=409, detail="All source branches must still be accepted")
    version = AnswerVersion(
        conversation_id=conversation_id,
        version_number=(latest.version_number + 1 if latest else 1),
        content=request.content.strip(),
        created_by="assistant",
    )
    db.add(version)
    db.flush()
    _add_message(db, conversation.id, "assistant", version.content, version.id)
    for branch in branches:
        db.add(
            AnswerVersionSource(
                answer_version_id=version.id,
                source_branch_id=branch.id,
                source_passage_id=branch.source_passage_id,
                relationship_type="merged_from",
            )
        )
    draft.confirmed_at = datetime.now(timezone.utc)
    conversation.updated_at = utcnow()
    db.commit()
    return _serialize_conversation(db, conversation)


@app.get("/api/conversations/{conversation_id}/graph")
def get_graph(conversation_id: str, db: Session = Depends(get_db)):
    conversation = _get_conversation(db, conversation_id)
    serialized = _serialize_conversation(db, conversation)
    nodes = []
    edges = []
    for message in serialized["messages"]:
        if message["role"] == "user":
            nodes.append({"id": message["id"], "type": "question", "label": message["content"][:90]})
        else:
            nodes.append({"id": message["id"], "type": "answer", "label": f"Answer v{next((v['version_number'] for v in serialized['versions'] if v['id'] == message['answer_version_id']), '?')}"})
            for passage in message["passages"]:
                nodes.append({"id": passage["id"], "type": "passage", "label": passage["content"][:90]})
                edges.append({"id": f"{message['id']}-{passage['id']}", "source": message["id"], "target": passage["id"], "label": "contains"})
        if message["role"] == "assistant":
            preceding = next((m for m in reversed(serialized["messages"][: serialized["messages"].index(message)]) if m["role"] == "user"), None)
            if preceding:
                edges.append({"id": f"{preceding['id']}-{message['id']}", "source": preceding["id"], "target": message["id"], "label": "answers"})
    for branch in serialized["branches"]:
        nodes.append({"id": branch["id"], "type": "branch_question", "label": f"Question · {branch['status']}: {branch['user_instruction'][:65]}", "status": branch["status"]})
        selections = branch["selections"] or [{"text": branch["source_passage"], "source_passage_ids": [branch["source_passage_id"]]}]
        for selection_index, selection in enumerate(selections):
            selection_id = f"{branch['id']}:selection:{selection_index}"
            nodes.append({"id": selection_id, "type": "selected_text", "label": selection["text"][:90], "branch_id": branch["id"]})
            for passage_id in selection["source_passage_ids"]:
                edges.append({"id": f"{passage_id}-{selection_id}", "source": passage_id, "target": selection_id, "label": "selected_from"})
            edges.append({"id": f"{selection_id}-{branch['id']}", "source": selection_id, "target": branch["id"], "label": "asks_about"})
        previous_id = branch["id"]
        for index, branch_message in enumerate(branch["messages"]):
            if index == 0 and branch_message["role"] == "user" and branch_message["content"] == branch["user_instruction"]:
                continue
            message_type = "branch_answer" if branch_message["role"] == "assistant" else "branch_followup"
            nodes.append({"id": branch_message["id"], "type": message_type, "label": branch_message["content"][:90], "branch_id": branch["id"]})
            edges.append({"id": f"{previous_id}-{branch_message['id']}", "source": previous_id, "target": branch_message["id"], "label": "answers" if message_type == "branch_answer" else "continues"})
            previous_id = branch_message["id"]
    branch_message_index = {
        message["id"]: message
        for branch in serialized["branches"]
        for message in branch["messages"]
        if message["role"] == "assistant"
    }
    for context_source in serialized["context_sources"]:
        assistant_sources = [
            message_id
            for message_id in context_source["source_branch_message_ids"]
            if message_id in branch_message_index
        ]
        if assistant_sources:
            branch_message_id = assistant_sources[-1]
            edges.append({
                "id": f"context-{branch_message_id}-{context_source['target_message_id']}",
                "source": branch_message_id,
                "target": context_source["target_message_id"],
                "label": "context_used",
            })
    return {"nodes": nodes, "edges": edges, "conversation_id": conversation.id}
