"""bootstrap migration infrastructure

Intentionally empty: verifies Alembic plumbing only. Feature tables arrive with the
database/authentication specification.

Revision ID: ad059f2b73c4
Revises:
Create Date: 2026-09-26 09:19:37.903609

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "ad059f2b73c4"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
