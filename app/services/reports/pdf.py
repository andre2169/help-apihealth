from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
from io import BytesIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


LABELS = {
    "open": "Aberto",
    "reopened": "Reaberto",
    "in_progress": "Em andamento",
    "resolved": "Resolvido",
    "closed": "Fechado",
    "low": "Baixa",
    "medium": "Média",
    "high": "Alta",
    "critical": "Crítica",
}

try:
    SAO_PAULO = ZoneInfo("America/Sao_Paulo")
except ZoneInfoNotFoundError:  # Windows minimal pode nao ter a base IANA.
    SAO_PAULO = timezone(timedelta(hours=-3))


def _safe_text(value, max_length: int = 90) -> str:
    text = str(value if value is not None else "Sem valor").strip()
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1]}..."


def _safe_paragraph_text(value, max_length: int = 90) -> str:
    return escape(_safe_text(value, max_length))


def _to_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _format_datetime(value) -> str:
    if isinstance(value, datetime):
        if value.tzinfo:
            value = value.astimezone(SAO_PAULO)
        else:
            value = value.replace(tzinfo=timezone.utc).astimezone(SAO_PAULO)
        return value.strftime("%d/%m/%Y %H:%M")
    return _safe_text(value)


def _format_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return value


def _format_short_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m")
    except ValueError:
        return value


def _period_label(filters: dict) -> str:
    start_date = filters.get("start_date")
    end_date = filters.get("end_date")
    if start_date and end_date:
        return f"{_format_date(start_date)} a {_format_date(end_date)}"
    return "Todo o historico"


def report_pdf_filename(filters: dict | None) -> str:
    filters = filters or {}
    start_date = filters.get("start_date") or "historico"
    end_date = filters.get("end_date") or datetime.now(SAO_PAULO).strftime("%Y-%m-%d")
    return f"helpweb-health-relatorio-{start_date}-a-{end_date}.pdf"


def _ranked_rows(data: dict | None, *, max_rows: int, preserve_order: bool = False):
    rows = [
        (LABELS.get(str(key), str(key or "Sem valor")), _to_int(value))
        for key, value in (data or {}).items()
    ]
    rows = [(label, total) for label, total in rows if total > 0]

    if not preserve_order:
        rows.sort(key=lambda item: (-item[1], item[0].lower()))

    if len(rows) <= max_rows:
        return rows

    selected = rows[:max_rows]
    other_total = sum(total for _, total in rows[max_rows:])
    if other_total:
        selected.append(("Outros", other_total))
    return selected


def _daily_rows(data: dict | None, *, max_rows: int):
    rows = [(_format_short_date(str(key)), _to_int(value)) for key, value in (data or {}).items()]
    rows = [(label, total) for label, total in rows if total > 0]
    if len(rows) <= max_rows:
        return rows

    previous_total = sum(total for _, total in rows[:-max_rows])
    selected = rows[-max_rows:]
    if previous_total:
        return [("Dias anteriores", previous_total), *selected]
    return selected


def _technician_rows(technicians: list[dict], *, max_rows: int):
    rows = sorted(
        technicians or [],
        key=lambda tech: (
            -(
                _to_int(tech.get("assigned_total"))
                + _to_int(tech.get("resolved_total"))
                + _to_int(tech.get("closed_total"))
            ),
            str(tech.get("name") or "").lower(),
        ),
    )
    if len(rows) <= max_rows:
        return rows

    selected = rows[:max_rows]
    remaining = rows[max_rows:]
    selected.append(
        {
            "name": "Demais tecnicos",
            "assigned_total": sum(_to_int(item.get("assigned_total")) for item in remaining),
            "resolved_total": sum(_to_int(item.get("resolved_total")) for item in remaining),
            "closed_total": sum(_to_int(item.get("closed_total")) for item in remaining),
        }
    )
    return selected


def build_reports_overview_pdf(data: dict) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover - depende da instalacao do deploy.
        raise RuntimeError("A dependência reportlab não está instalada.") from exc

    page_size = landscape(A4)
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=12 * mm,
        title="HelpWeb Health - Relatorio gerencial",
        author="HelpWeb Health",
    )
    content_width = page_size[0] - document.leftMargin - document.rightMargin
    card_gap = 4 * mm
    card_width = (content_width - card_gap) / 2

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=18,
            textColor=colors.HexColor("#182315"),
            spaceAfter=2,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionTitle",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=8.6,
            leading=10,
            textColor=colors.HexColor("#1c2b17"),
            spaceAfter=2,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SmallText",
            parent=styles["BodyText"],
            fontSize=7.2,
            leading=8.6,
            textColor=colors.HexColor("#53604e"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableText",
            parent=styles["BodyText"],
            fontSize=7,
            leading=8.2,
            textColor=colors.HexColor("#182315"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableNumber",
            parent=styles["BodyText"],
            alignment=TA_RIGHT,
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=8.2,
            textColor=colors.HexColor("#2f6426"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="KpiLabel",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=6.5,
            leading=7.8,
            textColor=colors.HexColor("#53604e"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="KpiValue",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=13,
            textColor=colors.HexColor("#2f6426"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="Footer",
            parent=styles["BodyText"],
            alignment=TA_CENTER,
            fontSize=6.5,
            leading=8,
            textColor=colors.HexColor("#6b7665"),
        )
    )

    def paragraph(value, style_name: str = "TableText", max_length: int = 90):
        return Paragraph(_safe_paragraph_text(value, max_length), styles[style_name])

    def metric_card(title: str, rows: dict | None, *, max_rows: int = 6, daily: bool = False):
        if daily:
            items = _daily_rows(rows, max_rows=max_rows)
        else:
            items = _ranked_rows(rows, max_rows=max_rows)

        table_rows = [[paragraph(title, "SectionTitle", 64), ""]]
        if not items:
            table_rows.append([paragraph("Sem dados para este recorte.", "SmallText", 80), ""])
        else:
            for key, value in items:
                table_rows.append([paragraph(key, max_length=70), paragraph(value, "TableNumber")])

        table = Table(
            table_rows,
            colWidths=[card_width - 17 * mm, 17 * mm],
            hAlign="LEFT",
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("SPAN", (0, 0), (-1, 0)),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef4e9")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d8e1d3")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        return table

    def metric_grid(cards):
        flowables = []
        for index in range(0, len(cards), 2):
            pair = Table(
                [[cards[index], cards[index + 1] if index + 1 < len(cards) else ""]],
                colWidths=[card_width, card_width],
                hAlign="LEFT",
            )
            pair.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (0, 0), card_gap),
                    ]
                )
            )
            flowables.append(pair)
            if index + 2 < len(cards):
                flowables.append(Spacer(1, 2))
        return flowables

    def technician_card(technicians: list[dict], *, max_rows: int = 6):
        rows = _technician_rows(technicians, max_rows=max_rows)
        table_rows = [[paragraph("Desempenho por tecnico", "SectionTitle", 64), "", "", ""]]
        if not rows:
            table_rows.append([paragraph("Sem dados para este recorte.", "SmallText", 80), "", "", ""])
        else:
            table_rows.append(
                [
                    paragraph("Tecnico", "KpiLabel"),
                    paragraph("Atr.", "KpiLabel"),
                    paragraph("Res.", "KpiLabel"),
                    paragraph("Fec.", "KpiLabel"),
                ]
            )
            for tech in rows:
                table_rows.append(
                    [
                        paragraph(tech.get("name"), max_length=50),
                        paragraph(tech.get("assigned_total"), "TableNumber"),
                        paragraph(tech.get("resolved_total"), "TableNumber"),
                        paragraph(tech.get("closed_total"), "TableNumber"),
                    ]
                )

        table = Table(
            table_rows,
            colWidths=[card_width - 42 * mm, 14 * mm, 14 * mm, 14 * mm],
            hAlign="LEFT",
            repeatRows=2 if len(table_rows) > 2 else 1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("SPAN", (0, 0), (-1, 0)),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef4e9")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d8e1d3")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        if len(table_rows) == 2:
            table.setStyle(TableStyle([("SPAN", (0, 1), (-1, 1))]))
        return table

    filters = data.get("filters") or {}
    metrics = data.get("summary_metrics") or {}
    sla = data.get("sla") or {}
    generated_at = _format_datetime(data.get("generated_at"))

    total_analyzed = _to_int(metrics.get("total_analyzed"))
    active_total = _to_int(metrics.get("active_total"))
    completed_total = _to_int(metrics.get("completed_total"))
    completed_percent = _to_int(metrics.get("completed_percent"))
    reopen_events = _to_int(metrics.get("reopen_events_count"))
    avg_resolution_hours = _to_int(metrics.get("avg_resolution_hours"))
    sla_within_total = _to_int(metrics.get("sla_within_total"))
    sla_resolved_total = _to_int(metrics.get("sla_resolved_total"))
    sla_within_percent = _to_int(metrics.get("sla_within_percent"))

    header = Table(
        [
            [
                [
                    Paragraph("HelpWeb Health", styles["SmallText"]),
                    Paragraph("Relatorio gerencial de chamados", styles["ReportTitle"]),
                    Paragraph(
                        "Indicadores consolidados de suporte tecnico para a operacao de TI em unidades de saude.",
                        styles["SmallText"],
                    ),
                ],
                [
                    Paragraph("<b>Gerado em</b>", styles["SmallText"]),
                    Paragraph(escape(generated_at), styles["SmallText"]),
                ],
            ]
        ],
        colWidths=[content_width - 45 * mm, 45 * mm],
        hAlign="LEFT",
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 1.2, colors.HexColor("#2f6426")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    filter_cells = [
        ("Periodo", _period_label(filters)),
        ("Status", LABELS.get(filters.get("status"), filters.get("status") or "Todos")),
        ("Prioridade", LABELS.get(filters.get("priority"), filters.get("priority") or "Todas")),
        ("Impacto", LABELS.get(filters.get("operational_impact"), filters.get("operational_impact") or "Todos")),
        ("Setor", filters.get("sector") or "Todos"),
        ("Categoria", filters.get("category") or "Todas"),
    ]
    filter_table = Table(
        [
            [
                [
                    Paragraph(f"<b>{escape(label)}</b>", styles["SmallText"]),
                    Paragraph(_safe_paragraph_text(value, 52), styles["TableText"]),
                ]
                for label, value in filter_cells[:3]
            ],
            [
                [
                    Paragraph(f"<b>{escape(label)}</b>", styles["SmallText"]),
                    Paragraph(_safe_paragraph_text(value, 52), styles["TableText"]),
                ]
                for label, value in filter_cells[3:]
            ],
        ],
        colWidths=[content_width / 3] * 3,
        hAlign="LEFT",
    )
    filter_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbfdf8")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d8e1d3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    def kpi_cell(label: str, value, caption: str):
        return [
            Paragraph(escape(label), styles["KpiLabel"]),
            Paragraph(_safe_paragraph_text(value, 28), styles["KpiValue"]),
            Paragraph(_safe_paragraph_text(caption, 46), styles["SmallText"]),
        ]

    kpi_table = Table(
        [
            [
                kpi_cell("Total analisado", total_analyzed, "Chamados no recorte"),
                kpi_cell("Fila ativa", active_total, "Abertos e em andamento"),
                kpi_cell("Concluidos", f"{completed_total} ({completed_percent}%)", "Resolvidos ou fechados"),
                kpi_cell("SLA vencido", _to_int(sla.get("overdue")), "Ativos fora do prazo"),
            ],
            [
                kpi_cell("Sem tecnico", _to_int(metrics.get("unassigned_active_total")), "Aguardando atribuicao"),
                kpi_cell("Reaberturas", reopen_events, "Eventos no recorte"),
                kpi_cell("Tempo medio", f"{avg_resolution_hours}h", "Resolucao dos chamados"),
                kpi_cell("SLA cumprido", f"{sla_within_total}/{sla_resolved_total}", f"{sla_within_percent}% dos resolvidos"),
            ],
        ],
        colWidths=[content_width / 4] * 4,
        hAlign="LEFT",
    )
    kpi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cddac7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    cards = [
        metric_card("Status", data.get("status_counts"), max_rows=6),
        metric_card("Prioridade", data.get("priority_counts"), max_rows=6),
        metric_card("Impacto operacional", data.get("impact_counts"), max_rows=6),
        metric_card("Situacao da fila", data.get("queue_snapshot"), max_rows=6),
        metric_card("Setores mais acionados", data.get("sector_counts"), max_rows=5),
        metric_card("Categorias mais recorrentes", data.get("category_counts"), max_rows=5),
        metric_card("Equipamentos recorrentes", data.get("equipment_counts"), max_rows=5),
        metric_card("Solicitantes recorrentes", data.get("requester_counts"), max_rows=5),
        metric_card("Evolucao recente por dia", data.get("daily_counts"), max_rows=6, daily=True),
        metric_card("Idade da fila ativa", data.get("active_age_counts"), max_rows=6),
    ]
    if data.get("technicians"):
        cards.append(technician_card(data.get("technicians") or [], max_rows=4))

    story = [
        header,
        Spacer(1, 5),
        filter_table,
        Spacer(1, 5),
        kpi_table,
        Spacer(1, 7),
        Paragraph("Indicadores consolidados", styles["SectionTitle"]),
        *metric_grid(cards),
    ]

    story.extend(
        [
            Spacer(1, 6),
            Paragraph(
                "Relatorio gerencial compacto: secoes extensas exibem os principais itens e consolidam o restante em 'Outros'. "
                "O documento apresenta apenas indicadores de suporte tecnico e nao deve conter dados de pacientes.",
                styles["SmallText"],
            ),
        ]
    )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(colors.HexColor("#6b7665"))
        canvas.drawCentredString(
            page_size[0] / 2,
            6 * mm,
            f"HelpWeb Health - Relatorio gerencial | Pagina {doc.page}",
        )
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
