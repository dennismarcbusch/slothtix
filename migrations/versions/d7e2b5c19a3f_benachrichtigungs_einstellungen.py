"""Benachrichtigungs-Einstellungen je Agent

Revision ID: d7e2b5c19a3f
Revises: c3f1a9d2e7b4
Create Date: 2026-10-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7e2b5c19a3f'
down_revision = 'c3f1a9d2e7b4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'mail_neue_tickets',
            sa.Enum('ALLE', 'AB_MITTEL', 'NUR_HOCH', 'KEINE', name='mailneuetickets'),
            server_default='ALLE',
            nullable=False,
        ))
        batch_op.add_column(sa.Column('mail_antworten', sa.Boolean(), server_default=sa.true(), nullable=False))
        batch_op.add_column(sa.Column('mail_zuweisung', sa.Boolean(), server_default=sa.true(), nullable=False))
        batch_op.add_column(sa.Column('zusammenfassung_aktiv', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('zusammenfassung_uhrzeit', sa.Time(), server_default='07:00:00.000000', nullable=False))
        batch_op.add_column(sa.Column('zusammenfassung_nur_werktags', sa.Boolean(), server_default=sa.true(), nullable=False))
        batch_op.add_column(sa.Column('zusammenfassung_gesendet_am', sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('zusammenfassung_gesendet_am')
        batch_op.drop_column('zusammenfassung_nur_werktags')
        batch_op.drop_column('zusammenfassung_uhrzeit')
        batch_op.drop_column('zusammenfassung_aktiv')
        batch_op.drop_column('mail_zuweisung')
        batch_op.drop_column('mail_antworten')
        batch_op.drop_column('mail_neue_tickets')
