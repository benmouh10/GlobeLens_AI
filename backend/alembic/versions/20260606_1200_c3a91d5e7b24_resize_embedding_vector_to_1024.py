"""resize_embedding_vector_to_1024

Narrows embeddings.vector from vector(1536) to vector(1024) so the column matches
the local Ollama bge-m3 embedding width. 1536 was sized for OpenAI
text-embedding-3-small, which is no longer the embedding backend.

Existing rows cannot be carried across the width change, so this migration
truncates the embeddings table. Re-run the batch embedding endpoint afterwards.

Revision ID: c3a91d5e7b24
Revises: f07290eae839
Create Date: 2026-06-06 12:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3a91d5e7b24'
down_revision: Union[str, None] = 'f07290eae839'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_DIMENSIONS = 1536
NEW_DIMENSIONS = 1024


def upgrade() -> None:
    # An IVFFlat index can only be built on a column of one fixed width, so the
    # index has to be dropped before the ALTER TYPE and rebuilt afterwards.
    op.execute("DROP INDEX IF EXISTS ix_embeddings_vector_ivfflat;")
    # Vectors of different widths cannot be cast across, so the rows have to go
    # before the column can be retyped. The table is emptied in both directions.
    op.execute("DELETE FROM embeddings;")
    op.execute(f"ALTER TABLE embeddings ALTER COLUMN vector TYPE vector({NEW_DIMENSIONS});")
    # lists=100 stays the target for datasets up to ~1M vectors. pgvector warns
    # that the index is ineffective until the table has rows; that is expected on
    # a fresh database and resolves after the first batch embedding run.
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_embeddings_vector_ivfflat
        ON embeddings
        USING ivfflat (vector vector_cosine_ops)
        WITH (lists = 100);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_embeddings_vector_ivfflat;")
    op.execute("DELETE FROM embeddings;")
    op.execute(f"ALTER TABLE embeddings ALTER COLUMN vector TYPE vector({OLD_DIMENSIONS});")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_embeddings_vector_ivfflat
        ON embeddings
        USING ivfflat (vector vector_cosine_ops)
        WITH (lists = 100);
        """
    )
