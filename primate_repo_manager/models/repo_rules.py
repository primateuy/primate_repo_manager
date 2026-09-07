# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Heurísticas como DATOS, no como código.

Dos cosas que el módulo tiene que adivinar —de qué tipo es un repo y qué rol cumple una
rama— dependen de convenciones que cambian y que, en la práctica, no se cumplen de forma
uniforme. Los defaults de este módulo no salen de la convención escrita sino de leer 503
ramas reales de 40 repos: ahí aparecieron tres grafías distintas de staging conviviendo
(`.staging`, `_staging`, `.Staging`), una rama de producción en español (`17.0.Produccion`)
y un `17.0.PRIMATE_support` con un segmento en mayúsculas.

Y una trampa que sólo se ve mirando los datos: existe `17.0.product_domain`. Un patrón
ingenuo de `prod` la clasificaría como rama de producción. Por eso los patrones están
anclados a separador o fin de cadena.
"""
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

CLASSIFICATIONS = [
	("localizacion", "Localización"),
	("cliente", "Cliente"),
	("interno", "Interno"),
	("fork_upstream", "Fork de upstream"),
]

BRANCH_ROLES = [
	("base", "Base de versión"),
	("staging", "Staging"),
	("support", "Support"),
	("prod", "Producción"),
	("version", "Rama de versión (otra)"),
	("mirror", "Espejo de upstream"),
	("patch", "Parches sobre fork"),
	("other", "Otra"),
]

# Los roles que la política gobierna, y por lo tanto los únicos contra los que tiene
# sentido medir cumplimiento o escribir un ruleset. Una rama «otra» o una de un fork sin
# migrar no es incumplimiento: no hay convención contra la cual medirla.
#
# Vive acá —y no en quien la usa— porque la usan el panel de salud y el armado de
# rulesets, y dos listas iguales en dos archivos se desincronizan el día que alguien
# agrega un rol. Esa desincronización no falla: mide una cosa y aplica otra.
ROLES_GOBERNADOS = ("base", "prod", "staging", "support")


class RepoClassificationRule(models.Model):
	_name = "repo.classification.rule"
	_inherit = ["repo.policy.audited"]
	_description = "Regla para clasificar un repositorio automáticamente"
	_order = "sequence, id"

	name = fields.Char(string="Nombre", required=True)
	sequence = fields.Integer(string="Secuencia", default=10)
	active = fields.Boolean(string="Activa", default=True)
	match_type = fields.Selection(
		[("is_fork", "Es un fork"),
		 ("name_regex", "El nombre matchea una expresión"),
		 ("visibility", "Visibilidad")],
		string="Condición", required=True, default="name_regex")
	value = fields.Char(
		string="Valor",
		help="Para 'nombre': la expresión regular. Para 'visibilidad': private o public. "
			 "Para 'es un fork': se ignora.")
	classification = fields.Selection(
		CLASSIFICATIONS, string="Clasificación", required=True)
	note = fields.Char(string="Por qué")

	@api.constrains("match_type", "value")
	def _check_regex(self):
		for regla in self:
			if regla.match_type == "name_regex":
				try:
					re.compile(regla.value or "")
				except re.error as exc:
					raise ValidationError(_(
						"La expresión de «%(nombre)s» no compila: %(error)s"
					) % {"nombre": regla.name, "error": exc}) from exc

	def _matches(self, datos_repo):
		"""¿Esta regla aplica al repo? `datos_repo` es el dict crudo de la API."""
		self.ensure_one()
		if self.match_type == "is_fork":
			return bool(datos_repo.get("fork"))
		if self.match_type == "visibility":
			privado = bool(datos_repo.get("private"))
			return (self.value or "").strip().lower() == ("private" if privado else "public")
		if self.match_type == "name_regex":
			nombre = datos_repo.get("name") or ""
			try:
				return bool(re.search(self.value or "", nombre))
			except re.error:
				# Una regla rota no puede tumbar una auditoría de 94 repos.
				_logger.warning("Repo Manager: regla de clasificación inválida: %s", self.name)
				return False
		return False

	@api.model
	def classify(self, datos_repo):
		"""Primera regla que matchea gana. None si ninguna: eso es un finding, no un default."""
		for regla in self.search([]):
			if regla._matches(datos_repo):
				return regla.classification
		return False


class RepoBranchRoleRule(models.Model):
	_name = "repo.branch.role.rule"
	_inherit = ["repo.policy.audited"]
	_description = "Regla para asignar el rol de una rama por su nombre"
	_order = "sequence, id"

	name = fields.Char(string="Nombre", required=True)
	sequence = fields.Integer(string="Secuencia", default=10)
	active = fields.Boolean(string="Activa", default=True)
	pattern = fields.Char(
		string="Expresión regular", required=True,
		help="Se evalúa con re.search sobre el nombre de la rama.")
	role = fields.Selection(BRANCH_ROLES, string="Rol", required=True)
	note = fields.Char(string="Por qué")

	@api.constrains("pattern")
	def _check_pattern(self):
		for regla in self:
			try:
				re.compile(regla.pattern or "")
			except re.error as exc:
				raise ValidationError(_(
					"La expresión de «%(nombre)s» no compila: %(error)s"
				) % {"nombre": regla.name, "error": exc}) from exc

	@api.model
	def regla_para(self, nombre_rama):
		"""La regla que le asigna el rol a esta rama, o vacío si ninguna.

		La pantalla de ramas muestra el rol Y de dónde salió —«Producción · regla 1»—
		porque un rol sin su origen es una afirmación que nadie puede discutir. Sale de
		acá y no de una segunda pasada por las reglas: dos recorridos con el mismo orden
		son dos hasta que alguien cambie uno.
		"""
		for regla in self.search([]):
			try:
				if re.search(regla.pattern, nombre_rama or ""):
					return regla
			except re.error:
				_logger.warning("Repo Manager: regla de rol de rama inválida: %s", regla.name)
		return self.browse()

	@api.model
	def role_for(self, nombre_rama):
		"""Rol de una rama. Primera regla que matchea gana; 'other' si ninguna."""
		return self.regla_para(nombre_rama).role or "other"
