from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: int
    table_name: str
    record_id: int
    action: str
    old_values: Optional[dict] = None
    new_values: Optional[dict] = None
    changed_fields: Optional[list] = None
    timestamp: Optional[datetime] = None
    source: Optional[str] = None
    user_id: Optional[int] = None
    username: Optional[str] = None

    model_config = {"from_attributes": True}
