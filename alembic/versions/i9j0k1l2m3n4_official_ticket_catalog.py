"""Create the official sector and category catalog without rewriting tickets."""

import unicodedata

from alembic import op
import sqlalchemy as sa


revision = "i9j0k1l2m3n4"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table(
        "ticket_catalog_options",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("normalized_name", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("kind", "normalized_name", name="uq_ticket_catalog_kind_name"),
        sa.CheckConstraint("kind IN ('sector', 'category')", name="ck_ticket_catalog_kind"),
    )
    defaults = {
        "sector": [
            "Recepção", "UTI", "Enfermaria", "Laboratório", "Farmácia",
            "Centro Cirúrgico", "Pronto Atendimento", "Radiologia", "Ambulatório",
            "Almoxarifado", "Administrativo", "TI",
        ],
        "category": [
            "Infraestrutura", "Rede", "Hardware", "Software hospitalar", "Impressão",
            "Acesso", "Telefonia", "Internet", "Segurança", "Periféricos",
            "Sistema de gestão hospitalar", "Leitor ou coletor",
        ],
    }
    rows = []
    for kind, names in defaults.items():
        for name in names:
            key = "".join(
                char for char in unicodedata.normalize("NFKD", name.casefold())
                if not unicodedata.combining(char)
            )
            rows.append({"kind": kind, "name": name, "normalized_name": key, "active": True})
    op.bulk_insert(table, rows)


def downgrade():
    op.drop_table("ticket_catalog_options")
