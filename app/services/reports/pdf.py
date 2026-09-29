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
    return "Todo o histórico"


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
            "name": "Demais técnicos",
            "assigned_total": sum(_to_int(item.get("assigned_total")) for item in remaining),
            "resolved_total": sum(_to_int(item.get("resolved_total")) for item in remaining),
            "closed_total": sum(_to_int(item.get("closed_total")) for item in remaining),
        }
    )
    return selected


def build_reports_overview_pdf(data: dict, *, viewer_role: str | None = None) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:  # pragma: no cover - depende da instalacao do deploy.
        raise RuntimeError("A dependência reportlab não está instalada.") from exc

    page_size = A4
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=13 * mm,
        bottomMargin=15 * mm,
        title="HelpWeb Health - Relatório de chamados",
        author="HelpWeb Health",
    )
    content_width = page_size[0] - document.leftMargin - document.rightMargin

    blue = colors.HexColor("#0D6EA8")
    ink = colors.HexColor("#10253A")
    muted = colors.HexColor("#668096")
    border = colors.HexColor("#DBE6EE")
    soft_blue = colors.HexColor("#E6F4FD")
    pale = colors.HexColor("#F5F9FC")
    green = colors.HexColor("#287A57")
    red = colors.HexColor("#B23A2E")

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=19,
            leading=22,
            alignment=0,
            textColor=ink,
            spaceAfter=2,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionTitle",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=ink,
            spaceBefore=3,
            spaceAfter=5,
            keepWithNext=True,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodySmall",
            parent=styles["BodyText"],
            fontSize=8.5,
            leading=11,
            textColor=muted,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableText",
            parent=styles["BodyText"],
            fontSize=8,
            leading=10,
            textColor=ink,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableNumber",
            parent=styles["BodyText"],
            alignment=TA_RIGHT,
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=ink,
        )
    )
    styles.add(
        ParagraphStyle(
            name="KpiLabel",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9,
            textColor=muted,
        )
    )
    styles.add(
        ParagraphStyle(
            name="KpiValue",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=18,
            textColor=blue,
        )
    )
    styles.add(
        ParagraphStyle(
            name="MetaRight",
            parent=styles["BodyText"],
            alignment=TA_RIGHT,
            fontSize=8,
            leading=11,
            textColor=muted,
        )
    )

    def paragraph(value, style_name: str = "TableText", max_length: int = 100):
        return Paragraph(_safe_paragraph_text(value, max_length), styles[style_name])

    def metric_table(title: str, values: dict | None, *, width: float, max_rows: int = 5, daily: bool = False, preserve_order: bool = False):
        if daily:
            rows = _daily_rows(values, max_rows=max_rows)
        else:
            rows = _ranked_rows(values, max_rows=max_rows, preserve_order=preserve_order)

        table_rows = [[paragraph(title, "TableText", 80), ""]]
        if not rows:
            table_rows.append([paragraph("Sem dados neste recorte.", "BodySmall", 80), ""])
        else:
            table_rows.extend(
                [paragraph(label, max_length=72), paragraph(total, "TableNumber")]
                for label, total in rows
            )

        table = Table(
            table_rows,
            colWidths=[width - 18 * mm, 18 * mm],
            hAlign="LEFT",
            repeatRows=1,
        )
        commands = [
            ("SPAN", (0, 0), (-1, 0)),
            ("BACKGROUND", (0, 0), (-1, 0), soft_blue),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, blue),
            ("LINEBELOW", (0, 1), (-1, -1), 0.35, border),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        if len(table_rows) == 2 and not rows:
            commands.append(("SPAN", (0, 1), (-1, 1)))
        table.setStyle(TableStyle(commands))
        return table

    def table_group(items: list[Table], widths: list[float], *, padding: float = 3 * mm):
        group = Table([items], colWidths=widths, hAlign="LEFT")
        group.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("LEFTPADDING", (1, 0), (-1, -1), padding),
                    ("RIGHTPADDING", (0, 0), (-2, -1), padding),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        return group

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

    if viewer_role == "admin":
        report_scope = "Visão consolidada da operação de suporte técnico."
    else:
        report_scope = "Visão dos chamados vinculados ao atendimento do técnico."

    header = Table(
        [[
            [
                Paragraph("HELPWEB HEALTH", styles["KpiLabel"]),
                Paragraph("Relatório de chamados", styles["ReportTitle"]),
                Paragraph(report_scope, styles["BodySmall"]),
            ],
            [
                Paragraph("<b>Gerado em</b>", styles["MetaRight"]),
                Paragraph(escape(generated_at), styles["MetaRight"]),
            ],
        ]],
        colWidths=[content_width - 43 * mm, 43 * mm],
        hAlign="LEFT",
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 1.5, blue),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    filter_items = [
        ("Período", _period_label(filters)),
        ("Status", LABELS.get(filters.get("status"), filters.get("status") or "Todos")),
        ("Prioridade", LABELS.get(filters.get("priority"), filters.get("priority") or "Todas")),
        ("Impacto", LABELS.get(filters.get("operational_impact"), filters.get("operational_impact") or "Todos")),
        ("Setor", filters.get("sector") or "Todos"),
        ("Categoria", filters.get("category") or "Todas"),
    ]
    filters_line = "  |  ".join(
        f"<b>{escape(label)}:</b> {_safe_paragraph_text(value, 48)}"
        for label, value in filter_items
    )
    filter_summary = Paragraph(f"<b>Filtros aplicados</b><br/>{filters_line}", styles["BodySmall"])

    def kpi_cell(label: str, value, color):
        value_style = ParagraphStyle(
            f"KpiValue{label.replace(' ', '')}",
            parent=styles["KpiValue"],
            textColor=color,
        )
        return [
            Paragraph(escape(label.upper()), styles["KpiLabel"]),
            Paragraph(_safe_paragraph_text(value, 28), value_style),
        ]

    kpi_table = Table(
        [[
            kpi_cell("Total analisado", total_analyzed, blue),
            kpi_cell("Fila ativa", active_total, blue),
            kpi_cell("Concluídos", f"{completed_total} ({completed_percent}%)", green),
            kpi_cell("SLA vencido", _to_int(sla.get("overdue")), red),
        ]],
        colWidths=[content_width / 4] * 4,
        hAlign="LEFT",
    )
    kpi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), pale),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, border),
                ("LINEBEFORE", (1, 0), (-1, -1), 0.5, border),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )

    secondary_items = [
        ("Sem técnico", _to_int(metrics.get("unassigned_active_total"))),
        ("Reaberturas", reopen_events),
        ("Tempo médio", f"{avg_resolution_hours}h"),
        ("SLA cumprido", f"{sla_within_percent}% ({sla_within_total}/{sla_resolved_total})"),
    ]
    secondary_table = Table(
        [[
            [Paragraph(escape(label), styles["BodySmall"]), Paragraph(f"<b>{escape(str(value))}</b>", styles["TableText"])]
            for label, value in secondary_items
        ]],
        colWidths=[content_width / 4] * 4,
        hAlign="LEFT",
    )
    secondary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), soft_blue),
                ("LINEBEFORE", (1, 0), (-1, -1), 0.5, border),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    third_width = content_width / 3
    half_width = content_width / 2
    story = [
        header,
        Spacer(1, 7),
        filter_summary,
        Spacer(1, 8),
        Paragraph("Resumo operacional", styles["SectionTitle"]),
        kpi_table,
        Spacer(1, 3),
        secondary_table,
        Spacer(1, 10),
        Paragraph("Distribuição", styles["SectionTitle"]),
        table_group(
            [
                metric_table("Por status", data.get("status_counts"), width=third_width, max_rows=5),
                metric_table("Por prioridade", data.get("priority_counts"), width=third_width, max_rows=4),
                metric_table("Por impacto", data.get("impact_counts"), width=third_width, max_rows=4),
            ],
            [third_width] * 3,
        ),
        Spacer(1, 9),
        Paragraph("Recorrências mais frequentes", styles["SectionTitle"]),
        table_group(
            [
                metric_table("Setores", data.get("sector_counts"), width=third_width, max_rows=4),
                metric_table("Categorias", data.get("category_counts"), width=third_width, max_rows=4),
                metric_table("Equipamentos", data.get("equipment_counts"), width=third_width, max_rows=4),
            ],
            [third_width] * 3,
        ),
        Spacer(1, 9),
        Paragraph("Fila e atividade recente", styles["SectionTitle"]),
        table_group(
            [
                metric_table("Situação da fila", data.get("queue_snapshot"), width=half_width, max_rows=4, preserve_order=True),
                metric_table("Idade dos chamados ativos", data.get("active_age_counts"), width=half_width, max_rows=4, preserve_order=True),
            ],
            [half_width, half_width],
            padding=4 * mm,
        ),
    ]

    daily_values = data.get("daily_counts") or {}
    if daily_values:
        story.extend(
            [
                Spacer(1, 9),
                KeepTogether(
                    [
                        Paragraph("Movimento recente", styles["SectionTitle"]),
                        metric_table("Chamados criados por dia", daily_values, width=content_width, max_rows=7, daily=True),
                    ]
                ),
            ]
        )

    technicians = data.get("technicians") or []
    if technicians:
        rows = _technician_rows(technicians, max_rows=5)
        table_rows = [[
            paragraph("Técnico", "KpiLabel"),
            paragraph("Atribuídos", "KpiLabel"),
            paragraph("Resolvidos", "KpiLabel"),
            paragraph("Fechados", "KpiLabel"),
        ]]
        table_rows.extend(
            [
                paragraph(row.get("name"), max_length=70),
                paragraph(row.get("assigned_total"), "TableNumber"),
                paragraph(row.get("resolved_total"), "TableNumber"),
                paragraph(row.get("closed_total"), "TableNumber"),
            ]
            for row in rows
        )
        technician_table = Table(
            table_rows,
            colWidths=[content_width - 63 * mm, 21 * mm, 21 * mm, 21 * mm],
            repeatRows=1,
            hAlign="LEFT",
        )
        technician_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), soft_blue),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.4, border),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        heading = "Atendimentos por técnico" if viewer_role == "admin" else "Atendimento do técnico"
        story.extend(
            [
                Spacer(1, 9),
                KeepTogether([Paragraph(heading, styles["SectionTitle"]), technician_table]),
            ]
        )

    story.extend(
        [
            Spacer(1, 7),
            Paragraph(
                "Relatório de gestão da infraestrutura de TI. As métricas respeitam os filtros e as permissões da conta; não incluem dados clínicos.",
                styles["BodySmall"],
            ),
        ]
    )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(muted)
        canvas.drawCentredString(
            page_size[0] / 2,
            7 * mm,
            f"HelpWeb Health  |  Relatório operacional  |  Página {doc.page}",
        )
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
