from typing import Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    debug: bool = False


class SelectionInput(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    source_passage_ids: list[str] = Field(min_length=1, max_length=12)


class BranchRequest(BaseModel):
    source_passage_id: str
    source_answer_version_id: str
    action_type: Literal["ask", "expand", "challenge"] = "ask"
    user_instruction: str = Field(min_length=1, max_length=4000)
    selections: list[SelectionInput] = Field(default_factory=list, max_length=12)
    debug: bool = False


class ContinueRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    debug: bool = False


class MergeRequest(BaseModel):
    branch_ids: list[str] = Field(min_length=1, max_length=10)


class ConfirmMergeRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
