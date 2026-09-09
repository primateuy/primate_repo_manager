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

EL CRON DE LA AUDITORÍA SE EDITA ACÁ Y NO EN *TÉCNICO*. Cambiar cuándo se audita es una
decisión de quien administra Repo Manager, no de quien administra Odoo, y el menú Técnico
—además de pedir `base.group_system`— muestra los crones de la instancia entera. La
elevación de permisos vale para UN registro, buscado por su identificador externo, y para
tres campos suyos: el mismo criterio acotado que las claves de configuración.

EL DIAGNÓSTICO responde con evidencia y no con configuración: ver `_compute_diagnostico`.
"""
import logging

from datetime import timedelta

import pytz

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

# El cron de la auditoría, por su identificador externo. Igual que `CLAVES`: la lista es
# el alcance de la elevación de permisos, y está fija en el código.
CRON_AUDITORIA = "primate_repo_manager.cron_auditoria_programada"

DIAS = [("0", "Lunes"), ("1", "Martes"), ("2", "Miércoles"), ("3", "Jueves"),
		("4", "Viernes"), ("5", "Sábado"), ("6", "Domingo")]

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

	# --- cuándo se audita sola ---
	audit_cron_active = fields.Boolean(
		string="Auditar automáticamente",
		help="Apagarlo no borra nada: las auditorías se siguen pudiendo lanzar a mano.")
	audit_cron_frequency = fields.Selection(
		[("days", "Todos los días"), ("weeks", "Todas las semanas"),
		 ("months", "Todos los meses")],
		string="Cada cuánto", default="weeks")
	audit_cron_weekday = fields.Selection(
		DIAS, string="Qué día", default="0",
		help="Sólo cuenta si la frecuencia es semanal.")
	audit_cron_hour = fields.Float(
		string="A qué hora", default=8.0,
		help="En tu zona horaria. Se guarda convertida a UTC, que es como Odoo programa "
			 "las tareas.")
	audit_cron_nextcall = fields.Char(
		string="Próxima corrida programada", compute="_compute_diagnostico",
		help="La hora real de la próxima, ya convertida a tu zona. Es la comprobación de "
			 "que lo que se guardó es lo que se entendió.")

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
		[("ok", "Íntegra"), ("rota", "ROTA"), ("vacia", "Sin entradas todavía"),
		 # «Pendiente» apareció cuando el sellado pasó a hacerse después del commit. Sin
		 # esta opción, el diagnóstico reventaba al asignar un valor que la selección no
		 # tenía — un estado nuevo del modelo que la pantalla no conocía.
		 ("pendiente", "Sellado pendiente")],
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

		cron = self._cron()
		if cron:
			valores["audit_cron_active"] = cron.active
			valores["audit_cron_frequency"] = cron.interval_type
			local = self._a_local(cron.nextcall)
			if local:
				valores["audit_cron_weekday"] = str(local.weekday())
				valores["audit_cron_hour"] = local.hour + local.minute / 60.0
		return valores

	@api.model
	def _cron(self):
		"""El cron de la auditoría, o vacío si alguien lo borró.

		Se busca por identificador externo y con `sudo()`: leer `ir.cron` pide ser
		administrador de Odoo, y quien administra Repo Manager no tiene por qué serlo.
		`raise_if_not_found=False` porque un cron borrado a mano no puede hacer que la
		pantalla de configuración entera deje de abrir.
		"""
		return self.env.ref(CRON_AUDITORIA, raise_if_not_found=False).sudo()

	def _zona(self):
		"""La zona horaria de quien está mirando. UTC si no declaró ninguna."""
		return pytz.timezone(self.env.user.tz or "UTC")

	def _a_local(self, naive_utc):
		"""UTC ingenuo —como lo guarda Odoo— a hora local de quien mira."""
		if not naive_utc:
			return False
		return pytz.utc.localize(naive_utc).astimezone(self._zona())

	def _proxima_corrida(self, ahora=None):
		"""La próxima vez que caiga ese día y esa hora, en UTC ingenuo.

		POR QUÉ SE CALCULA Y NO SE ESCRIBE «lunes 08:00» EN EL CAMPO. `ir.cron.nextcall`
		es un instante en UTC, no una regla; escribirlo con la hora local haría que la
		auditoría corriera a las 5 de la mañana en verano y a las 6 en invierno sin que
		nadie tocara nada. La zona horaria es la de quien guarda, que es quien dijo
		«ocho de la mañana» pensando en su reloj.
		"""
		self.ensure_one()
		zona = self._zona()
		ahora = ahora or fields.Datetime.now()
		local = pytz.utc.localize(ahora).astimezone(zona)
		hora = int(self.audit_cron_hour)
		minuto = int(round((self.audit_cron_hour - hora) * 60))
		objetivo = local.replace(
			hour=min(hora, 23), minute=min(minuto, 59), second=0, microsecond=0)
		if self.audit_cron_frequency == "weeks":
			deseado = int(self.audit_cron_weekday or "0")
			adelanto = (deseado - objetivo.weekday()) % 7
			objetivo += timedelta(days=adelanto)
		if objetivo <= local:
			objetivo += timedelta(days=7 if self.audit_cron_frequency == "weeks" else 1)
		return objetivo.astimezone(pytz.utc).replace(tzinfo=None)

	def action_save(self):
		"""Guarda SÓLO las claves de `CLAVES`. El `sudo()` vale para esa lista."""
		self.ensure_one()
		if not self.env.user.has_group("primate_repo_manager.group_repo_admin"):
			raise UserError(_(
				"Sólo un administrador de Repo Manager puede cambiar estos valores."))
		Config = self.env["ir.config_parameter"].sudo()
		for campo, clave in CLAVES.items():
			Config.set_param(clave, str(self[campo]))

		cron = self._cron()
		if cron:
			# TRES CAMPOS DE UN REGISTRO, y el registro se busca por su identificador
			# externo. Es el mismo alcance fijo que `CLAVES`: no hay forma de que esta
			# pantalla escriba otro cron de la instancia.
			cron.write({
				"active": self.audit_cron_active,
				"interval_number": 1,
				"interval_type": self.audit_cron_frequency,
				"nextcall": self._proxima_corrida(),
			})
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
			cadena = self.env["repo.audit.log"].estado_de_la_cadena()
			ajustes.chain_state = cadena["estado"]
			ajustes.chain_detail = cadena["detalle"]

			# La próxima corrida, en la zona de quien mira. Es la comprobación de que
			# lo guardado es lo entendido: «lunes 08:00» escrito y «lunes 08:00» leído.
			cron = self._cron()
			local = ajustes._a_local(cron.nextcall) if cron else False
			if not cron:
				ajustes.audit_cron_nextcall = _(
					"El cron de la auditoría no está: alguien lo borró. Se puede seguir "
					"auditando a mano.")
			elif not cron.active:
				ajustes.audit_cron_nextcall = _(
					"Apagado. Las auditorías sólo corren cuando alguien las lanza.")
			else:
				ajustes.audit_cron_nextcall = local.strftime("%A %d/%m/%Y %H:%M") if local \
					else _("Programado sin fecha.")

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
