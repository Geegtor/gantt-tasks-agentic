from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator


class MoveTask(BaseModel):
    op: Literal["move_task"] = "move_task"
    task_id: str
    delta_days: int


class ResizeTask(BaseModel):
    op: Literal["resize_task"] = "resize_task"
    task_id: str
    delta_days: int  # positive = extend duration, negative = shorten


class SwapTasks(BaseModel):
    op: Literal["swap_tasks"] = "swap_tasks"
    task_a_id: str
    task_b_id: str
    swap_dependencies: bool = False


class AddTask(BaseModel):
    op: Literal["add_task"] = "add_task"
    name: str
    description: str = ""
    assignee: str = ""
    duration_days: int = Field(default=1)
    predecessor_ids: list[str] = Field(default_factory=list)

    @field_validator("duration_days", mode="before")
    @classmethod
    def at_least_one_day(cls, v: object) -> int:
        """Clamp LLM-supplied 0 or None to 1; Task model requires >= 1."""
        try:
            return max(1, int(v))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 1


class DeleteTask(BaseModel):
    op: Literal["delete_task"] = "delete_task"
    task_id: str


class SetDependency(BaseModel):
    op: Literal["set_dependency"] = "set_dependency"
    task_id: str
    predecessor_ids: list[str]


class ReassignTask(BaseModel):
    op: Literal["reassign_task"] = "reassign_task"
    task_id: str
    new_assignee: str


class RenameTask(BaseModel):
    op: Literal["rename_task"] = "rename_task"
    task_id: str
    new_name: str
    new_description: str | None = None


class Answer(BaseModel):
    op: Literal["answer"] = "answer"
    text: str


class Clarify(BaseModel):
    op: Literal["clarify"] = "clarify"
    question: str


Command = Annotated[
    Union[
        MoveTask,
        ResizeTask,
        SwapTasks,
        AddTask,
        DeleteTask,
        SetDependency,
        ReassignTask,
        RenameTask,
        Answer,
        Clarify,
    ],
    Field(discriminator="op"),
]


class CommandBatch(BaseModel):
    commands: list[Command]
    summary: str = ""
