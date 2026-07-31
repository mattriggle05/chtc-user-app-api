from typing import Optional

from pydantic import ConfigDict, Field

from userapp.core.schemas.general import BaseModel

class UserSubmitGet(BaseModel):
    """A submit node a user has access to, derived from group membership. Quota fields are removed for now - see SubmitNode.group_id."""

    model_config = ConfigDict(extra='ignore')

    # From UserGroup
    user_id: int

    # From SubmitNode
    id: int
    name: str
    group_id: Optional[int] = Field(default=None)

class UserSubmitPost(BaseModel):
    """Requests that the user be granted access to this submit node via its group (SubmitNode.group_id)."""

    submit_node_id: int
