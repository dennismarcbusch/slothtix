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

SPALTEN = (
    'mail_neue_tickets',
    'mail_antworten',
    'mail_zuweisung',
    'zusammenfassung_aktiv',
    'zusammenfassung_uhrzeit',
    'zusammenfassung_nur_werktags',
    'zusammenfassung_gesendet_am',
)


def upgrade():
    # Bewusst kein batch_alter_table: Der baut die Tabelle neu auf und
    # löscht dafür die alte. Auf "user" verweisen Tickets, Kommentare und
    # Team-Mitgliedschaften; mit PRAGMA foreign_keys=ON scheitert das DROP
    # dann mit "FOREIGN KEY constraint failed". Reines ADD COLUMN kann
    # SQLite ohne Neuaufbau.
    #
    # Ein abgebrochener Lauf der ersten Fassung dieser Migration hat eine
    # halbfertige Kopie hinterlassen - die räumen wir weg.
    op.execute('DROP TABLE IF EXISTS _alembic_tmp_user')

    op.add_column('user', sa.Column(
        'mail_neue_tickets',
        sa.Enum('ALLE', 'AB_MITTEL', 'NUR_HOCH', 'KEINE', name='mailneuetickets'),
        server_default='ALLE',
        nullable=False,
    ))
    op.add_column('user', sa.Column('mail_antworten', sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column('user', sa.Column('mail_zuweisung', sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column('user', sa.Column('zusammenfassung_aktiv', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('user', sa.Column('zusammenfassung_uhrzeit', sa.Time(), server_default='07:00:00.000000', nullable=False))
    op.add_column('user', sa.Column('zusammenfassung_nur_werktags', sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column('user', sa.Column('zusammenfassung_gesendet_am', sa.Date(), nullable=True))


def downgrade():
    # ALTER TABLE ... DROP COLUMN (SQLite >= 3.35), ebenfalls ohne Neuaufbau.
    for spalte in reversed(SPALTEN):
        op.drop_column('user', spalte)
