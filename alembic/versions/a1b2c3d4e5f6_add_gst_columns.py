"""add GST columns to invoice_lines and bill_lines

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-04-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

gst_enum = sa.Enum("taxable", "gst_free", "input_taxed", "n/a", name="gstclassification")


def upgrade() -> None:
    # Create the enum type
    gst_enum.create(op.get_bind(), checkfirst=True)

    # Add GST columns to invoice_lines
    op.add_column("invoice_lines", sa.Column(
        "gst_classification", gst_enum, nullable=True, server_default="taxable",
    ))
    op.add_column("invoice_lines", sa.Column(
        "gst_amount", sa.Numeric(12, 2), nullable=True, server_default="0",
    ))

    # Add GST columns to bill_lines
    op.add_column("bill_lines", sa.Column(
        "gst_classification", gst_enum, nullable=True, server_default="taxable",
    ))
    op.add_column("bill_lines", sa.Column(
        "gst_amount", sa.Numeric(12, 2), nullable=True, server_default="0",
    ))


def downgrade() -> None:
    op.drop_column("bill_lines", "gst_amount")
    op.drop_column("bill_lines", "gst_classification")
    op.drop_column("invoice_lines", "gst_amount")
    op.drop_column("invoice_lines", "gst_classification")
    gst_enum.drop(op.get_bind(), checkfirst=True)
