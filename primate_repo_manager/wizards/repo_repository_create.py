# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El asistente de nacimiento gobernado — página 6b del entregable.

TRES PASOS, COMO EL MOCKUP: identidad, gobernanza, confirmar. Y el botón del final dice
«Revisar el plan y crear», no «Crear»: **el asistente no escribe en GitHub**. Arma un plan
y lo abre. Un asistente que creara directo sería la única escritura del módulo sin embudo,
y justo la que crea objetos nuevos — los que después nadie puede deshacer.

EL PASO 3 MUESTRA LO QUE SE VA A CREAR, ENTERO. No un «se van a aplicar 9 operaciones»
sino cuáles, con sus nombres. Quien decide tiene que poder leer la lista antes de apretar,
no descubrirla en la bitácora.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.repo_rules import CLASSIFICATIONS

_logger = logging.getLogger(__name__)


class RepoRepositoryCreateWizard(models.TransientModel):
	_name = "repo.repository.create.wizard"
	_description = "Crear un repositorio ya gobernado"

	backend_id = fields.Many2one(
		"repo.backend", string="Conexión", required=True,
		domain=[("state", "=", "connected")])
	base = fields.Char(
		string="Cliente o producto", required=True,
		help="Cómo lo llama la gente. El nombre del repositorio lo arma la convención.")
	classification = fields.Selection(
		CLASSIFICATIONS, string="Clasificación", required=True,
		help="Se elige a mano. De ella salen el prefijo del nombre y la plantilla de "
			 "política que se aplica.")
	version = fields.Char(string="Versión", default="19.0", required=True)
	member_id = fields.Many2one(
		"repo.member", string="Responsable",
		help="Queda con permiso de administración sobre el repositorio.")
	private = fields.Boolean(string="Privado", default=True)

	nombre_previsto = fields.Char(
		string="Nombre del repositorio", compute="_compute_resumen",
		help="Lo arma la regla de nombres de la clasificación elegida.")
	resumen_html = fields.Html(string="Lo que se crea", compute="_compute_resumen")
	problema = fields.Char(string="Problema", compute="_compute_resumen")

	@api.depends("base", "classification", "version", "private", "member_id")
	def _compute_resumen(self):
		"""El paso 3, calculado en vivo. Y si algo no cierra, se dice ACÁ.

		Un asistente que deja apretar y falla después obliga a leer un error para
		entender que faltaba un dato. Lo que impide crear se muestra mientras se elige.
		"""
		for asistente in self:
			asistente.nombre_previsto = False
			asistente.resumen_html = False
			asistente.problema = False
			if not (asistente.base and asistente.classification):
				continue
			try:
				resumen = self.env["repo.write.plan"].resumen_de_nacimiento({
					"base": asistente.base,
					"clasificacion": asistente.classification,
					"version": asistente.version,
					"privado": asistente.private,
					"responsable": asistente.member_id,
				})
			except UserError as exc:
				asistente.problema = str(exc)
				continue
			asistente.nombre_previsto = resumen["nombre"]
			asistente.resumen_html = asistente._dibujar(resumen)

	def _dibujar(self, resumen):
		"""El resumen, en las palabras del mockup y sin inventar tranquilidad."""
		self.ensure_one()
		ramas = " · ".join(resumen["ramas"])
		gobernadas = ", ".join(resumen["ramas_gobernadas"])
		responsable = (
			_("%s administra") % self.member_id.github_login if self.member_id
			else _("sin responsable asignado: nadie queda con administración"))
		return _(
			"<ul>"
			"<li><b>%(cuantas)s ramas</b>: <span class='rm-mono'>%(ramas)s</span></li>"
			"<li><b>%(gobernadas)s protegidas desde el primer minuto</b>, con lo que "
			"exige la plantilla «%(plantilla)s»</li>"
			"<li>%(responsable)s</li>"
			"<li>%(visibilidad)s, con README y las alertas de Dependabot encendidas</li>"
			"</ul>"
			"<p>%(operaciones)s operaciones. La creación del repositorio "
			"<b>no se puede deshacer</b>; las demás sí.</p>"
		) % {
			"cuantas": len(resumen["ramas"]), "ramas": ramas,
			"gobernadas": gobernadas or _("ninguna"),
			"plantilla": resumen["plantilla"], "responsable": responsable,
			"visibilidad": _("Privado") if resumen["privado"] else _("Público"),
			"operaciones": resumen["operaciones"],
		}

	def action_armar_plan(self):
		"""«Revisar el plan y crear»: arma el plan y lo abre. No escribe en GitHub."""
		self.ensure_one()
		if self.problema:
			raise UserError(self.problema)
		plan = self.env["repo.write.plan"].armar_nacimiento(self.backend_id, {
			"base": self.base,
			"clasificacion": self.classification,
			"version": self.version,
			"privado": self.private,
			"responsable": self.member_id,
		})
		accion = self.env["ir.actions.actions"]._for_xml_id(
			"primate_repo_manager.action_repo_write_plan")
		accion.update({"res_id": plan.id, "views": [(False, "form")]})
		return accion
