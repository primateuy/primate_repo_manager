# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Política, personas y configuración: las garantías que no se ven en pantalla.

La más importante es la primera: **todo cambio de política queda en la bitácora
inmutable**. Cambiar la política es la escritura más silenciosa del módulo —no toca un
solo repositorio y redefine qué cuenta como incumplimiento para todos— así que es
justamente la que más necesita rastro.
"""
import uuid

from odoo.tests.common import TransactionCase


class TestBitacoraDePolitica(TransactionCase):

	def setUp(self):
		super().setUp()
		self.Log = self.env["repo.audit.log"]
		self.plantilla = self.env["repo.policy.template"].create({
			"name": "Plantilla %s" % uuid.uuid4().hex[:6],
			"code": "tpl-%s" % uuid.uuid4().hex[:6],
			"required_approvals": 2,
		})

	def _entradas(self):
		return self.Log.search([("event_type", "=", "policy_changed")], order="id desc")

	# --- EL test, y su mutación --------------------------------------------

	def test_cambiar_una_exigencia_queda_en_la_bitacora(self):
		"""Bajar «aprobaciones requeridas» de 2 a 1 hace desaparecer hallazgos sin
		arreglar nada. Tiene que quedar quién, cuándo, qué campo y de qué a qué.

		MUTACIÓN OBLIGATORIA: quitando la llamada a `_registrar_cambio_de_politica` del
		`write` de `repo.policy.audited`, este test se pone rojo.
		"""
		antes = len(self._entradas())
		self.plantilla.required_approvals = 1

		entradas = self._entradas()
		self.assertEqual(len(entradas), antes + 1, "el cambio no quedó registrado")
		entrada = entradas[0]
		self.assertIn(self.plantilla.name, entrada.summary)

		import json
		cambios = json.loads(entrada.payload_json)["cambios"]
		self.assertEqual(len(cambios), 1)
		etiqueta, valores = next(iter(cambios.items()))
		self.assertEqual(etiqueta, "Aprobaciones requeridas",
						 "la entrada nombra el campo como se lee en pantalla")
		self.assertEqual(valores["antes"], 2)
		self.assertEqual(valores["después"], 1)

	def test_la_entrada_de_politica_es_igual_de_inmutable_que_las_demas(self):
		"""No hay razón para que ésta se pueda reescribir y las de GitHub no."""
		from odoo.exceptions import UserError

		self.plantilla.required_approvals = 1
		entrada = self._entradas()[0]
		with self.assertRaises(UserError):
			entrada.sudo().write({"summary": "otra cosa"})
		with self.assertRaises(UserError):
			entrada.sudo().unlink()

	def test_se_registra_TODO_campo_que_cambie_sin_lista_blanca(self):
		"""Una lista de «campos importantes» es una lista que alguien va a olvidar de
		actualizar el día que agregue el campo que importaba."""
		antes = len(self._entradas())
		self.plantilla.write({
			"require_signed_commits": True,
			"branch_name_pattern": "^(17|19)\\\\.0",
		})
		entradas = self._entradas()
		self.assertEqual(len(entradas), antes + 1, "un write, una entrada")
		import json
		cambios = json.loads(entradas[0].payload_json)["cambios"]
		self.assertEqual(len(cambios), 2)

	def test_un_write_que_no_cambia_nada_no_ensucia_la_bitacora(self):
		"""Guardar un formulario sin tocar nada no es una decisión."""
		antes = len(self._entradas())
		self.plantilla.write({"required_approvals": 2})   # ya valía 2
		self.assertEqual(len(self._entradas()), antes)

	def test_los_valores_se_guardan_como_se_leen(self):
		"""«push -> admin» se entiende; «2 -> 4» obliga a ir a buscar la tabla."""
		import json

		regla = self.env["repo.policy.access.rule"].create({
			"template_id": self.plantilla.id,
			"member_id": self.env["repo.member"].create({
				"github_login": "quien-%s" % uuid.uuid4().hex[:6]}).id,
			"max_permission": "push", "reason": "porque sí",
		})
		regla.max_permission = "admin"
		cambios = json.loads(self._entradas()[0].payload_json)["cambios"]
		valores = cambios["Permiso máximo"]
		self.assertEqual(valores["antes"], "Escritura (push)")
		self.assertEqual(valores["después"], "Administrador")

	def test_las_reglas_de_clasificacion_tambien_estan_vigiladas(self):
		"""Cambiar una regla de clasificación cambia contra qué plantilla se compara un
		repositorio entero. Es tan de política como la plantilla misma."""
		antes = len(self._entradas())
		regla = self.env["repo.classification.rule"].create({
			"name": "R %s" % uuid.uuid4().hex[:6], "match_type": "name_regex",
			"value": "^prueba", "classification": "interno",
		})
		self.assertEqual(len(self._entradas()), antes + 1, "crear una regla se registra")
		regla.classification = "cliente"
		self.assertEqual(len(self._entradas()), antes + 2)
		regla.unlink()
		self.assertEqual(len(self._entradas()), antes + 3, "borrarla también")

	def test_los_datos_que_vienen_con_el_modulo_no_ensucian(self):
		"""Instalar no es decidir: el alta de los datos del módulo no se registra."""
		antes = len(self._entradas())
		self.env["repo.classification.rule"].with_context(install_mode=True).create({
			"name": "De instalación", "match_type": "is_fork",
			"classification": "fork_upstream",
		})
		self.assertEqual(len(self._entradas()), antes)


class TestAlcanceDeLaPlantilla(TransactionCase):

	def test_una_plantilla_dice_a_cuantos_gobierna(self):
		"""Una plantilla sin saber a quién le aplica es un formulario de configuración."""
		backend = self.env["repo.backend"].create({
			"name": "Alcance %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2"})
		plantilla = self.env["repo.policy.template"].create({
			"name": "Interno", "code": "int-%s" % uuid.uuid4().hex[:6],
			"classification_default": "interno"})
		antes = plantilla.repository_count
		for n in range(2):
			self.env["repo.repository"].create({
				"backend_id": backend.id, "name": "r%s" % n,
				"full_name": "%s/r%s" % (backend.owner_login, n),
				"github_id": uuid.uuid4().hex[:8], "classification": "interno"})
		plantilla.invalidate_recordset()
		self.assertEqual(plantilla.repository_count, antes + 2)


class TestPropuestaDeEmpleado(TransactionCase):
	"""Propone y una persona confirma. Nunca vincula solo.

	NO SE CREAN EMPLEADOS ACÁ, y conviene explicar por qué para que nadie lo "arregle".
	Crear un `hr.employee` arrastra la creación de un `res.partner`, y un partner arrastra
	medio ERP. En esta base de staging eso además revienta: el registro que arma la suite
	de tests omite unos 19 módulos instalados —`purchase_stock` entre ellos— mientras la
	columna `res_partner.group_rfq` que ese módulo declara sigue en la tabla con su
	`NOT NULL`. Ningún partner se puede insertar dentro de un test.

	Se reutiliza un empleado que ya existe y se le ajusta el mail dentro de la
	transacción, que es un UPDATE y no un INSERT. Lo que se prueba —que proponga por mail
	y por nombre, y que no vincule solo— no depende de haberlo creado nosotros.
	"""

	def setUp(self):
		super().setUp()
		self.persona = self.env["repo.member"].create({
			"github_login": "jperez", "name": "Juan Pérez"})
		self.empleado = self.env["hr.employee"].search([], limit=1)
		self.assertTrue(
			self.empleado,
			"la base no tiene ningún empleado y este test necesita uno; ver el docstring")
		self.nombre_original = self.empleado.name
		self.mail_original = self.empleado.work_email

	def test_propone_por_mail_de_trabajo(self):
		self.empleado.work_email = "jperez@primate.uy"
		self.persona.invalidate_recordset()
		self.assertIn(self.empleado, self.persona.employee_suggestion_ids)

	def test_propone_por_nombre(self):
		self.empleado.name = "Juan Pérez"
		self.persona.invalidate_recordset()
		self.assertIn(self.empleado, self.persona.employee_suggestion_ids)

	def test_NO_vincula_solo_ni_con_una_sola_coincidencia(self):
		"""La coincidencia es una pista, no una prueba: hay homónimos, y un login puede no
		tener nada que ver con el nombre de nadie. Un vínculo equivocado pone los permisos
		de una persona a nombre de otra, y eso se descubre sacando la conclusión
		contraria a la verdadera."""
		self.empleado.write({"name": "Juan Pérez", "work_email": "jperez@primate.uy"})
		self.persona.invalidate_recordset()
		self.assertTrue(self.persona.employee_suggestion_ids, "tiene que proponer")
		self.assertFalse(self.persona.employee_id,
						 "pero NO puede haber vinculado nada por su cuenta")

	def test_el_asistente_exige_elegir(self):
		from odoo.exceptions import UserError

		asistente = self.env["repo.member.link.wizard"].create({
			"member_id": self.persona.id})
		with self.assertRaises(UserError):
			asistente.action_confirm()

	def test_al_confirmar_queda_vinculado_y_dicho(self):
		asistente = self.env["repo.member.link.wizard"].create({
			"member_id": self.persona.id, "employee_id": self.empleado.id})
		asistente.action_confirm()
		self.assertEqual(self.persona.employee_id, self.empleado)

	def test_una_cuenta_ya_vinculada_no_recibe_propuestas(self):
		self.empleado.work_email = "jperez@primate.uy"
		self.persona.employee_id = self.empleado
		self.persona.invalidate_recordset()
		self.assertFalse(self.persona.employee_suggestion_ids)


class TestDiagnosticoDeAjustes(TransactionCase):
	"""El diagnóstico responde con evidencia, no con configuración."""

	def _ajustes(self):
		return self.env["repo.settings"].create({})

	def test_la_pantalla_NO_es_res_config_settings(self):
		"""`res.config.settings` exige ser administrador de Odoo entero. Un admin de Repo
		Manager abría la pantalla y recibía un Access Error; darle `base.group_system`
		para que pudiera mover un umbral sería cambiar un problema chico por uno grande.

		MUTACIÓN: apuntar el menú de vuelta a `res.config.settings` y este test avisa.
		"""
		accion = self.env.ref("primate_repo_manager.action_repo_config_settings")
		self.assertEqual(accion.res_model, "repo.settings")

	def test_sin_el_grupo_no_se_guarda_aunque_se_llegue_al_modelo(self):
		"""El ACL es la primera capa; ésta es la segunda. Un `sudo()` sobre parámetros
		merece las dos."""
		from odoo.exceptions import UserError

		ajustes = self._ajustes()
		self.assertFalse(self.env.user.has_group(
			"primate_repo_manager.group_repo_admin"))
		with self.assertRaises(UserError):
			ajustes.action_save()

	def test_solo_se_escriben_las_claves_declaradas(self):
		"""El guardado usa sudo() porque escribir parámetros pide ser administrador. Lo
		que hace que eso no sea un agujero es que el alcance esté fijo en el código."""
		from ..models.repo_settings import CLAVES

		self.assertTrue(all(c.startswith("repo_manager.") for c in CLAVES.values()),
						"ninguna clave fuera del espacio del módulo")

	def test_guardar_deja_los_valores(self):
		# La guarda del guardado exige el grupo explícitamente y no se conforma con el
		# ACL: es lo que acota el `sudo()` con el que se escriben los parámetros.
		self.env.user.group_ids = [(4, self.env.ref(
			"primate_repo_manager.group_repo_admin").id)]
		ajustes = self._ajustes()
		ajustes.sync_threshold = 7
		ajustes.action_save()
		self.assertEqual(
			self.env["ir.config_parameter"].sudo().get_param(
				"repo_manager.sync_threshold"), "7")

	def test_la_clave_de_cifrado_se_reporta_sin_mostrarse(self):
		ajustes = self._ajustes()
		self.assertTrue(ajustes.key_loaded,
						"esta instancia tiene repo_manager_key en odoo.conf")
		from odoo.tools import config
		self.assertNotIn(config.get("repo_manager_key") or "@@", ajustes.key_detail,
						 "el detalle NO puede filtrar la clave")

	def test_sin_tareas_no_se_afirma_que_funciona(self):
		"""Afirmar que el procesador anda sin una sola tarea procesada sería inventar."""
		self.env.cr.execute("DELETE FROM queue_job")
		self.env["queue.job"].invalidate_model()
		ajustes = self._ajustes()
		self.assertEqual(ajustes.runner_state, "sin_datos")

	def test_tareas_esperando_hace_rato_se_reportan_como_atasco(self):
		"""Es el modo de falla real: la corrida se queda «En curso» para siempre."""
		from datetime import timedelta

		from odoo import fields as odoo_fields

		self.env.cr.execute("DELETE FROM queue_job")
		self.env["queue.job"].invalidate_model()
		vieja = odoo_fields.Datetime.now() - timedelta(hours=1)
		self.env.cr.execute(
			"""INSERT INTO queue_job (uuid, name, state, model_name, method_name,
				 date_created, func_string, channel, records)
			   VALUES (%s, 'x', 'pending', 'repo.audit.run', 'x', %s, 'x', 'root', '{}')""",
			(uuid.uuid4().hex, vieja))
		self.env["queue.job"].invalidate_model()
		ajustes = self._ajustes()
		self.assertEqual(ajustes.runner_state, "atascado")
		self.assertIn("En curso", ajustes.runner_detail)
