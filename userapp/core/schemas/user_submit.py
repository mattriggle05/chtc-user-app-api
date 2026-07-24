from typing import Optional

from pydantic import ConfigDict, Field

from userapp.core.schemas.general import BaseModel

class UserSubmitGet(BaseModel):
    """A submit node a user has access to, derived from group membership:
    the submit node's own fields plus the user_id it's being viewed for.
    Quota fields are removed for now - they will move to a dedicated table keyed
    on (user, submit_node) in a future change."""

    model_config = ConfigDict(extra='ignore')

    user_id: int
    id: int
    name: str
    group_id: Optional[int] = Field(default=None)

class UserSubmitPost(BaseModel):
    """Requests that the user be granted access to this submit node. Implemented
    by adding the user to the submit node's associated group (SubmitNode.group_id)."""

    submit_node_id: int
