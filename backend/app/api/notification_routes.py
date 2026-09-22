from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import require_roles
from app.core.notification_manager import notification_manager
from app.core.persistence import list_citizen_notifications, mark_citizen_notification_read

router = APIRouter(prefix="/api", tags=["Notifications"])


@router.get("/citizen/notifications")
def citizen_notifications(user: dict = Depends(require_roles("CITIZEN"))):
    """Phase 6F2 Task E: persisted, citizen-scoped notifications (a separate
    write-through table from the legacy officer/admin notification_manager
    -- see CitizenNotificationRow's docstring for why)."""
    return {"notifications": list_citizen_notifications(user["citizenId"])}


@router.get("/officer/notifications")
def officer_notifications(user: dict = Depends(require_roles("OFFICER"))):
    return {"notifications": notification_manager.for_user(user)}


@router.get("/admin/notifications")
def admin_notifications(user: dict = Depends(require_roles("ADMIN"))):
    return {"notifications": notification_manager.for_user(user)}


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: str, user: dict = Depends(require_roles("CITIZEN", "OFFICER", "ADMIN"))):
    if notification_id.startswith("CN-"):
        item = mark_citizen_notification_read(notification_id, user["citizenId"]) if user["role"] == "CITIZEN" else None
    else:
        item = notification_manager.mark_read(notification_id, user)
    if not item:
        raise HTTPException(status_code=404, detail="Notification not found for this user.")
    return item
