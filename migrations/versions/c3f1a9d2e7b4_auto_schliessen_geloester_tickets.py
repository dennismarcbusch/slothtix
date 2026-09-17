"""Gelöste Tickets automatisch schließen

Revision ID: c3f1a9d2e7b4
Revises: 25ff72ef792a
Create Date: 2026-09-17 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3f1a9d2e7b4'
down_revision = '25ff72ef792a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('auto_schliessen_tage', sa.Integer(), server_default='14', nullable=False))
        batch_op.add_column(sa.Column('auto_schliessen_geprueft_am', sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table('ticket_history', schema=None) as batch_op:
        batch_op.alter_column('ausgefuehrt_von_id',
               existing_type=sa.INTEGER(),
               nullable=True)


def downgrade():
    # Automatische Einträge haben keinen ausführenden Nutzer und passen
    # nicht mehr in die NOT-NULL-Spalte.
    op.execute("DELETE FROM ticket_history WHERE ausgefuehrt_von_id IS NULL")
    with op.batch_alter_table('ticket_history', schema=None) as batch_op:
        batch_op.alter_column('ausgefuehrt_von_id',
               existing_type=sa.INTEGER(),
               nullable=False)

    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.drop_column('auto_schliessen_geprueft_am')
        batch_op.drop_column('auto_schliessen_tage')
