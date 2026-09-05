# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""La pantalla de configuración de Repo Manager, y el diagnóstico de la instancia.

POR QUÉ NO ES `res.config.settings`, QUE ERA LO OBVIO. Se hizo así primero y la pantalla
tiraba **Access Error** apenas la abría alguien que no fuera administrador de Odoo:
`res.config.settings` exige `base.group_system`, que da acceso a la administración entera
de la instancia —usuarios, permisos, parámetros de todos los módulos—. Quien administra
Repo Manager no tiene por qué ser eso, y darle ese grupo para que pueda mover un umbral
sería cambiar un problema chico por uno grande.

Lo destapó una captura para la guía. Desde el código no se veía: la vista cargaba bien.

EL PERMISO ELEVADO ESTÁ ACOTADO A PROPÓSITO. Escribir en `ir.config_parameter` también
pide ser administrador, así que el guardado usa `sudo()`. Lo que hace que eso no sea un
agujero es que **sólo escribe las cuatro claves que este modelo declara**: no hay forma de
pasarle otra por parámetro. El gate es el modelo, y el alcance está fijo en el código.

EL DIAGNÓSTICO responde con evidencia y no con configuración: ver `_compute_diagnostico`.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .res_config_settings import DEFAULTS

_logger = logging.getLogger(__name__)

# Las únicas claves que esta pantalla puede tocar. La elevación de permisos del guardado
# vale exactamente para esta lista y para nada más.
CLAVES = {
	"sync_threshold": "repo_manager.sync_threshold",
	"commit_violation_ratio": "repo_manager.commit_violation_ratio",
	"fork_behind_threshold": "repo_manager.fork_behind_threshold",
	"pr_stale_days": "repo_manager.pr_stale_days",
}

# Cuántos minutos puede esperar una tarea antes de que eso signifique que nadie la está
# atendiendo. Holgado a propósito: un pico de trabajo no es una avería.
ESPERA_SOSPECHOSA = 5


class RepoSettings(models.TransientModel):
	_name = "repo.settings"
	_description = "Configuración de Repo Manager"

	sync_threshold = fields.Integer(
		string="Auditar en el momento hasta",
		help="Por debajo de esta cantidad de repositorios la auditoría se hace de una y "
			 "la pantalla espera. Por encima, el trabajo se reparte en tareas.\n\n"
			 "El valor por defecto sale de una medición: 11,5 segundos por repositorio "
			 "en la cuenta real.")
	commit_violation_ratio = fields.Integer(
		string="% de commits fuera de convención que eleva la severidad",
		help="Por encima de este porcentaje el hallazgo sube de medio a alto: veinte "
			 "commits mal no es lo mismo que uno.")
	fork_behind_threshold = fields.Integer(
		string="Commits de atraso que elevan la severidad de un fork",
		help="A esa distancia el merge de parches ya es un problema y no un pendiente.")
	pr_stale_days = fields.Integer(
		string="Días para considerar estancada una PR")

	# --- diagnóstico, sólo lectura ---
	runner_state = fields.Selection(
		[("ok", "Funcionando"), ("atascado", "Hay tareas esperando"),
		 ("sin_datos", "Sin tareas todavía")],
		string="Procesamiento en segundo plano", compute="_compute_diagnostico")
	runner_detail = fields.Char(string="Detalle", compute="_compute_diagnostico")
	key_loaded = fields.Boolean(
		string="Clave de cifrado cargada", compute="_compute_diagnostico")
	key_detail = fields.Char(string="Detalle de la clave", compute="_compute_diagnostico")
	chain_state = fields.Selection(
		[("ok", "Íntegra"), ("rota", "ROTA"), ("vacia", "Sin entradas todavía")],
		string="Cadena de la bitácora", compute="_compute_diagnostico")
	chain_detail = fields.Char(
		string="Detalle de la cadena", compute="_compute_diagnostico")

	@api.model
	def default_get(self, campos):
		valores = super().default_get(campos)
		Config = self.env["ir.config_parameter"].sudo()
		for campo, clave in CLAVES.items():
			crudo = Config.get_param(clave, DEFAULTS[clave])
			try:
				valores[campo] = int(crudo)
			except (TypeError, ValueError):
				valores[campo] = int(DEFAULTS[clave])
		return valores

	def action_save(self):
		"""Guarda SÓLO las claves de `CLAVES`. El `sudo()` vale para esa lista."""
		self.ensure_one()
		if not self.env.user.has_group("primate_repo_manager.group_repo_admin"):
			raise UserError(_(
				"Sólo un administrador de Repo Manager puede cambiar estos valores."))
		Config = self.env["ir.config_parameter"].sudo()
		for campo, clave in CLAVES.items():
			Config.set_param(clave, str(self[campo]))
		return {"type": "ir.actions.act_window_close"}

	@api.depends_context("uid")
	def _compute_diagnostico(self):
		"""Se mira la EVIDENCIA, no la configuración.

		Preguntar si el hilo del procesador existe sólo funciona cuando corre dentro del
		proceso web; con `workers` mayor que cero vive en otro proceso y la respuesta sería
		«no» estando todo bien. Las tareas, en cambio, cuentan lo mismo en cualquier
		despliegue: si hay trabajo esperando hace rato, nadie lo está atendiendo, y da
		igual dónde debería estar corriendo el que no está.
		"""
		Job = self.env["queue.job"].sudo()
		ahora = fields.Datetime.now()
		esperando = Job.search(
			[("state", "in", ("pending", "enqueued"))], order="date_created", limit=1)
		ultima = Job.search([("state", "=", "done")], order="date_done desc", limit=1)
		minutos = ((ahora - esperando.date_created).total_seconds() / 60
				   if esperando and esperando.date_created else 0)

		for ajustes in self:
			if esperando and minutos >= ESPERA_SOSPECHOSA:
				ajustes.runner_state = "atascado"
				ajustes.runner_detail = _(
					"Hay tareas esperando desde hace %s minutos. Una auditoría encolada "
					"se va a quedar «En curso» sin avanzar hasta que esto se resuelva."
				) % int(minutos)
			elif ultima:
				ajustes.runner_state = "ok"
				ajustes.runner_detail = _(
					"La última tarea se procesó el %s.") % ultima.date_done
			else:
				ajustes.runner_state = "sin_datos"
				ajustes.runner_detail = _(
					"Todavía no se procesó ninguna tarea, así que no hay con qué afirmar "
					"que funciona. Lanzá una auditoría y volvé a mirar.")

			# La cadena de la bitácora. Es lo único del diagnóstico que puede acusar a
			# alguien: si está rota, alguien escribió en la base por fuera de Odoo.
			cadena = self.env["repo.audit.log"].verificar_cadena()
			ajustes.chain_state = cadena["estado"]
			if cadena["estado"] == "ok":
				ajustes.chain_detail = _(
					"Íntegra desde el %(desde)s · %(n)s entradas verificadas."
				) % {"desde": cadena["desde"], "n": cadena["entradas"]}
			elif cadena["estado"] == "rota":
				ajustes.chain_detail = _(
					"ROTA en la entrada %(id)s (%(momento)s): %(motivo)s. Alguien escribió "
					"en la base por fuera de la aplicación."
				) % {"id": cadena["entrada"], "momento": cadena["momento"],
					 "motivo": cadena["motivo"]}
			else:
				ajustes.chain_detail = _(
					"Todavía no hay entradas encadenadas que verificar.")

			# La clave NO se lee ni se muestra: sólo se responde si está.
			try:
				self.env["repo.backend"]._fernet()
				ajustes.key_loaded = True
				ajustes.key_detail = _(
					"Cargada en el archivo del servidor. No se muestra ni se edita desde "
					"acá, a propósito.")
			except Exception:  # noqa: BLE001
				ajustes.key_loaded = False
				ajustes.key_detail = _(
					"Falta `repo_manager_key` en odoo.conf, o es demasiado corta. Sin "
					"ella no se pueden leer las credenciales de las GitHub Apps: las "
					"conexiones existentes van a fallar al usarse.")
