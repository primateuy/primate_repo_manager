# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Muestra acotada de commits por rama principal.

Los entregables piden el formato de commit y la firma "de los últimos N commits de cada
rama principal". Se persiste una MUESTRA, no la historia: un repo con años de trabajo
tiene decenas de miles de commits y traerlos todos no agrega nada al informe.
"""
import re

from odoo import api, fields, models

# Formato de la convención: [ADD]/[IMP]/[FIX] con número de ticket.
# Se guarda como parámetro del backend en F3; acá es el default de la spec.
COMMIT_PATTERN = r"^\[(ADD|IMP|FIX)\]\[\d+\] .+"


class RepoCommitSample(models.Model):
	_name = "repo.commit.sample"
	_description = "Commit de la muestra auditada"
	_order = "committed_at desc"

	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio", required=True,
		ondelete="cascade", index=True)
	branch_name = fields.Char(string="Rama", required=True, index=True)
	sha = fields.Char(string="SHA", required=True, index=True)
	message_first_line = fields.Char(string="Mensaje")
	author_login = fields.Char(string="Autor")
	committed_at = fields.Datetime(string="Fecha")

	message_ok = fields.Boolean(
		string="Cumple el formato",
		help="Contra la expresión de la plantilla de política del repo.")
	signed = fields.Boolean(string="Firmado")
	signature_reason = fields.Char(
		string="Estado de la firma",
		help="Lo que reporta GitHub: valid, unsigned, unknown_key…")

	_commit_uniq = models.Constraint(
		"UNIQUE (repository_id, branch_name, sha)",
		"Ese commit ya está en la muestra de esa rama.")

	@api.model
	def message_matches(self, mensaje, patron=None):
		"""¿El mensaje cumple el formato? Tolera un patrón inválido sin tumbar el sync."""
		try:
			return bool(re.match(patron or COMMIT_PATTERN, mensaje or ""))
		except re.error:
			return False
