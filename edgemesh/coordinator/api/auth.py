import os

from fastapi import Header, HTTPException, status

_SECRET_HEADER = "X-EdgeMesh-Secret"


def require_agent_secret(
    x_edgemesh_secret: str | None = Header(default=None, alias=_SECRET_HEADER),
) -> None:
    expected = os.getenv("EDGE_MESH_SHARED_SECRET", "").strip()
    if not expected:
        return

    if x_edgemesh_secret != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing shared secret",
        )
