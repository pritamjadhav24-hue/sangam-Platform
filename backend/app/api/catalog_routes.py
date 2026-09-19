from fastapi import APIRouter, Depends

from app.core.auth import require_roles
from app.core.persistence import catalog_snapshot

router = APIRouter(prefix="/api/catalog", tags=["Catalog"])


@router.get("")
def catalog(user: dict = Depends(require_roles("OFFICER", "ADMIN"))):
    return catalog_snapshot()
