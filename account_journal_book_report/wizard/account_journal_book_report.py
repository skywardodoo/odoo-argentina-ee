##############################################################################
# For copyright and license notices, see __manifest__.py file in root directory
##############################################################################
import base64
import csv
import io

from markupsafe import Markup
from odoo import api, fields, models


class AccountJournalBookReport(models.TransientModel):
    _name = "account.journal.book.report"
    _inherit = "base.bg"
    _description = "Journal Book Report"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)

    journal_ids = fields.Many2many(
        comodel_name="account.journal",
        relation="account_journal_book_journal_rel",
        column1="acc_journal_entries_id",
        column2="journal_id",
        required=True,
        default=lambda self: self.env["account.journal"].search([("company_id", "=", self.company_id.id)]),
        domain="[('company_id', '=', company_id)]",
    )
    last_entry_number = fields.Integer(
        string="Último nº de asiento",
        required=True,
        default=0,
    )
    date_from = fields.Date(
        string="Start Date",
        required=True,
    )
    date_to = fields.Date(
        string="End Date",
        required=True,
    )

    target_move = fields.Selection(
        [
            ("posted", "All Posted Entries"),
            ("all", "All Entries"),
        ],
        string="Target Moves",
        required=True,
        default="posted",
    )

    @api.onchange("company_id")
    def _onchange_company_id(self):
        if dates := self.company_id.compute_fiscalyear_dates(fields.Date.from_string(fields.Date.today())):
            self.date_from = dates["date_from"]
            self.date_to = dates["date_to"]

    def _get_move_domain(self):
        domain = [
            ("company_id", "=", self.company_id.id),
            ("journal_id", "in", self.journal_ids.ids),
        ]
        if self.target_move == "posted":
            domain.append(("state", "=", "posted"))
        if self.date_from:
            domain.append(("date", ">=", self.date_from))
        if self.date_to:
            domain.append(("date", "<=", self.date_to))
        return domain

    def _generate_csv_attachment(self):
        """Generate a CSV fallback for journal book report without report_aeroo."""
        moves = self.env["account.move"].search(self._get_move_domain(), order="date, id")
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")

        writer.writerow(
            [
                "Fecha",
                "Asiento",
                "Diario",
                "Referencia",
                "Partner",
                "Cuenta",
                "Etiqueta",
                "Debe",
                "Haber",
                "Balance",
            ]
        )
        for move in moves:
            lines = move.line_ids.filtered(lambda line: not line.display_type)
            for line in lines:
                writer.writerow(
                    [
                        fields.Date.to_string(move.date) or "",
                        move.name or "",
                        move.journal_id.display_name or "",
                        move.ref or "",
                        line.partner_id.display_name or "",
                        line.account_id.display_name or "",
                        line.name or "",
                        line.debit or 0.0,
                        line.credit or 0.0,
                        line.balance or 0.0,
                    ]
                )

        csv_bytes = buffer.getvalue().encode("utf-8")
        return self.env["ir.attachment"].create(
            {
                "name": "account_journal_book_report.csv",
                "datas": base64.b64encode(csv_bytes),
                "res_model": self._name,
                "type": "binary",
                "company_id": self.company_id.id,
            }
        )

    def action_check_report(self):
        """Este método se llama desde el botón 'Imprimir' del wizard 'Libro Diario'"""
        self.ensure_one()
        if not self._context.get("bg_job"):
            res, _ = self.bg_enqueue("action_check_report")
            return res
        attachment = self._generate_csv_attachment()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        download_url = f"{base_url}/web/content/{attachment.id}?download=true"
        res_html = f"""
            The following document has been generated:<br>
            <a href="{download_url}" target="_blank">{attachment.name}</a>
        """
        return Markup(res_html)
