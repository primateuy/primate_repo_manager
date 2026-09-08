# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""B5.1 · los tres tipos del nacimiento gobernado.

El que manda: **crear un repositorio es irreversible, y es una decisión**. GitHub tiene
endpoint para borrarlos; este módulo no lo usa. Entre que el rollback lee y borra cabe un
push de otro, y no hay verificación previa que cierre esa ventana.
"""
import json
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from .test_backend import _clave_rsa_de_prueba
from .test_write_apply import Respuesta, Transporte, _aprobar_plan, sin_cursor_aparte


class TestNacimiento(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		self.env.user.group_ids |= self.env.ref("primate_repo_manager.group_repo_lead")
		self.backend = self.env["repo.backend"].create({
			"name": "Nac %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"environment": "sandbox"})
		self.backend.private_key = self.clave
		self.backend.write_app_id = "10"
		self.backend.write_installation_id = "20"
		self.backend.write_private_key = self.clave
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx", "full_name": "org/sbx", "default_branch": "19.0"})
		sin_cursor_aparte(self)

	def _op(self, kind, payload=None, target=False):
		plan = self.env["repo.write.plan"].create({
			"name": "Nacer", "backend_id": self.backend.id})
		op = self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": kind, "repository_id": self.repo.id,
			"target": target, "payload_json": json.dumps(payload or {})})
		return plan, op

	# ------------------------------------------------------------------
	# LO IRREVERSIBLE, que es la decisión del paso
	# ------------------------------------------------------------------

	def test_crear_un_repositorio_es_IRREVERSIBLE(self):
		"""Y se declara NO poniendo `revertir`: el hecho, no una lista."""
		_plan, op = self._op("repository_create", {"name": "cliente-nuevo"})
		self.assertTrue(op.is_supported)
		self.assertTrue(op.is_irreversible)

	def test_el_manejador_no_tiene_NINGUN_camino_para_borrar_un_repositorio(self):
		"""La garantía es estructural, como la del secreto: no hay dónde."""
		manejador = self.env["repo.write.operation"]._manejadores()["repository_create"]
		self.assertNotIn("revertir", manejador)
		import inspect

		from ..models import repo_write_apply
		fuente = inspect.getsource(repo_write_apply)
		self.assertNotIn('cliente.delete("/repos/%s" %', fuente)

	def test_las_otras_dos_SI_se_deshacen(self):
		"""Lo que se puede deshacer se deshace: el repositorio queda, visible y vacío."""
		for kind in ("branch_create", "dependabot_enable"):
			_plan, op = self._op(kind, target="19.0-dev")
			self.assertFalse(op.is_irreversible, kind)

	# ------------------------------------------------------------------
	# Crear el repositorio
	# ------------------------------------------------------------------

	def _correr(self, plan, gets, escrituras=None):
		transporte = Transporte(gets, escrituras)
		transporte.abarca = ["org/sbx"]
		Backend = type(self.backend)
		original = Backend.write_client
		Backend.write_client = lambda s, transport=None: original(
			s, transport=transporte)
		try:
			plan.action_apply()
		except UserError as exc:
			self.ultimo_error = str(exc)
		finally:
			Backend.write_client = original
		return transporte

	def test_si_el_repositorio_YA_EXISTE_no_se_vuelve_a_crear(self):
		"""Crear no es idempotente: si ya está, lo que corresponde es gobernarlo."""
		plan, op = self._op("repository_create", {"name": "ya-esta"})
		_aprobar_plan(plan)
		# DOS respuestas iguales, y no una: el ciclo lee el estado previo y `ejecutar`
		# vuelve a leer justo antes de crear —que es lo correcto, porque entre las dos
		# lecturas cabe que alguien lo cree—. El doble responde por cola, así que
		# guionar una sola lo hacía contestar 404 en la segunda y el guardián quedaba
		# evadido por el fixture, no por el código.
		transporte = self._correr(plan, gets=[
			Respuesta(200, {"id": 5, "name": "ya-esta"}),
			Respuesta(200, {"id": 5, "name": "ya-esta"})])
		self.assertEqual(transporte.escrituras_hechas(), [])
		self.assertIn("ya existe", self.ultimo_error)

	def test_en_una_cuenta_de_USUARIO_se_niega_con_el_motivo(self):
		"""Un token de App no puede crear repos en una cuenta de usuario: no hay
		endpoint. Negarse con el motivo es mejor que un 404 que nadie sabe leer."""
		self.backend.owner_type = "user"
		plan, _op = self._op("repository_create", {"name": "nuevo"})
		_aprobar_plan(plan)
		transporte = self._correr(plan, gets=[Respuesta(404, {"message": "Not Found"})])
		self.assertEqual(transporte.escrituras_hechas(), [])
		self.assertIn("cuenta de usuario", self.ultimo_error)

	def test_nace_con_README_porque_sin_rama_no_hay_donde_crear_las_demas(self):
		plan, _op = self._op("repository_create", {"name": "nuevo"})
		_aprobar_plan(plan)
		transporte = self._correr(plan, gets=[
			Respuesta(404, {"message": "Not Found"}),
			Respuesta(404, {"message": "Not Found"}),
			Respuesta(200, {"id": 9, "name": "nuevo"}),
		], escrituras={"POST": Respuesta(201, {
			# LA FORMA REAL: GitHub devuelve `full_name`, y el espejo lo exige. El doble
			# devolvía sólo id y name, y con eso el upsert reventaba contra un NOT NULL
			# — un doble que imita media respuesta miente en la mitad que no imita.
			"id": 9, "name": "nuevo", "full_name": "org/nuevo", "private": True,
			"default_branch": "main"})})
		cuerpos = [c for c in transporte.cuerpos if c[0] == "POST"]
		self.assertTrue(cuerpos)
		self.assertTrue(cuerpos[0][2]["auto_init"])
		self.assertTrue(cuerpos[0][2]["private"])

	# ------------------------------------------------------------------
	# Las ramas y Dependabot
	# ------------------------------------------------------------------

	def test_una_rama_que_ya_existe_no_se_recrea(self):
		plan, op = self._op("branch_create", target="19.0-dev")
		_aprobar_plan(plan)
		transporte = self._correr(plan, gets=[
			Respuesta(200, {"object": {"sha": "abc"}}),
			Respuesta(200, {"object": {"sha": "abc"}}),
			Respuesta(200, {"object": {"sha": "abc"}}),
			Respuesta(200, {"object": {"sha": "abc"}}),
			Respuesta(200, {"object": {"sha": "abc"}}),
			Respuesta(200, {"object": {"sha": "abc"}}),
		])
		self.assertEqual(transporte.escrituras_hechas(), [])
		self.assertEqual(op.state, "applied", op.error or "")

	def test_revertir_una_rama_que_YA_ESTABA_no_la_borra(self):
		"""Si estaba antes de que llegáramos no es nuestra: la regla del ajeno, en ref."""
		_plan, op = self._op("branch_create", target="19.0-dev")
		transporte = Transporte([])
		cliente = self.backend.write_client(transport=transporte)
		op._revertir_rama_creada(cliente, {"ya_existia": True, "nombre": "19.0-dev"})
		self.assertEqual(
			[c for c in transporte.llamadas if c[0] == "DELETE"], [])

	def test_revertir_sin_saber_QUE_rama_no_borra_ninguna(self):
		_plan, op = self._op("branch_create", target="19.0-dev")
		cliente = self.backend.write_client(transport=Transporte([]))
		with self.assertRaises(UserError):
			op._revertir_rama_creada(cliente, {"ya_existia": False})

	def test_dependabot_ya_encendido_no_se_reenciende(self):
		plan, op = self._op("dependabot_enable")
		_aprobar_plan(plan)
		transporte = self._correr(plan, gets=[
			Respuesta(204, None), Respuesta(204, None), Respuesta(204, None)])
		self.assertEqual(transporte.escrituras_hechas(), [])
		self.assertEqual(op.state, "applied", op.error or "")

	def test_revertir_dependabot_NO_lo_apaga_si_ya_estaba_encendido(self):
		"""Encenderlo no fue nuestro: apagarlo sería sacar algo que ya estaba."""
		_plan, op = self._op("dependabot_enable")
		transporte = Transporte([])
		cliente = self.backend.write_client(transport=transporte)
		op._revertir_dependabot(cliente, {"encendido": True})
		self.assertEqual([c for c in transporte.llamadas if c[0] == "DELETE"], [])

	def test_revertir_dependabot_lo_apaga_si_lo_prendimos_nosotros(self):
		_plan, op = self._op("dependabot_enable")
		transporte = Transporte([])
		cliente = self.backend.write_client(transport=transporte)
		op._revertir_dependabot(cliente, {"encendido": False})
		self.assertTrue([c for c in transporte.llamadas if c[0] == "DELETE"])


class TestRulesetsDerivadosDeLaPlantilla(TransactionCase):
	"""Qué protege el nacimiento lo dice la plantilla efectiva, y nadie más."""

	def setUp(self):
		super().setUp()
		self.plantilla = self.env["repo.policy.template"].search(
			[("classification_default", "=", "cliente")], limit=1)
		self.assertTrue(self.plantilla, "el módulo declara una plantilla de cliente")

	def test_un_rol_que_la_politica_no_gobierna_no_lleva_ruleset(self):
		"""`19.0-dev` es trabajo sobre una versión: ninguna política lo nombra.

		Escribirle un ruleset sería gobierno que nadie declaró; reclamárselo sería un
		hallazgo el día uno. Las dos preguntas se contestan con la misma llamada.
		"""
		armados = self.env["repo.write.plan"]._rulesets_de_nacimiento(
			self.plantilla, ["19.0-prod", "19.0-staging", "19.0-support", "19.0-dev"])
		roles = [rol for rol, _ramas, _a in armados]
		self.assertNotIn("version", roles)
		self.assertEqual(sorted(roles), ["prod", "staging", "support"])

	def test_dos_ramas_del_MISMO_rol_son_UN_ruleset_y_el_resumen_lo_sabe(self):
		"""El armado siempre creó un ruleset por ROL y el resumen contaba RAMAS.

		Con las cuatro ramas de hoy los dos números coinciden por casualidad —una rama
		por rol— y por eso nadie lo vio. En cuanto dos ramas comparten rol, el número
		prometido queda uno arriba del armado, y el número prometido es el único que
		alguien mira antes de apretar.
		"""
		armados = self.env["repo.write.plan"]._rulesets_de_nacimiento(
			self.plantilla, ["19.0-prod", "19.0-produccion"])
		self.assertEqual(len(armados), 1, "dos ramas del mismo rol son un solo ruleset")
		_rol, ramas, _a = armados[0]
		self.assertEqual(sorted(ramas), ["19.0-prod", "19.0-produccion"])

	def test_sin_plantilla_no_se_inventa_gobierno(self):
		armados = self.env["repo.write.plan"]._rulesets_de_nacimiento(
			self.env["repo.policy.template"], ["19.0-prod"])
		self.assertEqual(armados, [])


class TestNombreYVuelta(TransactionCase):
	"""B5.2 · el prefijo, y la guarda que hace imposible nacer mal clasificado."""

	def setUp(self):
		super().setUp()
		self.Reglas = self.env["repo.classification.rule"]

	# ------------------------------------------------------------------
	# LA IDA Y VUELTA
	# ------------------------------------------------------------------

	def test_TODA_regla_con_prefijo_clasifica_de_vuelta_a_su_clasificacion(self):
		"""La guarda no es sobre tres casos: es sobre lo que haya configurado.

		Si generador y clasificador divergen, el repo nace mal clasificado en su primer
		segundo — y ninguna auditoría posterior sabría que fue de nacimiento. Recorrer
		las reglas con prefijo, y no una lista escrita acá, hace que la regla que alguien
		agregue mañana quede cubierta por existir.
		"""
		con_prefijo = self.Reglas.search([("name_prefix", "!=", False)])
		self.assertTrue(con_prefijo, "tiene que haber al menos una regla con prefijo")
		for regla in con_prefijo:
			nombre = self.Reglas.nombre_para(regla.classification, "Mutualista Casmu")
			self.assertEqual(
				self.Reglas.classify({"name": nombre, "full_name": nombre}),
				regla.classification,
				"«%s» no vuelve a «%s»" % (nombre, regla.classification))

	def test_los_prefijos_se_sembraron_en_las_reglas_que_ya_existian(self):
		"""Una base vieja y una recién instalada tienen que comportarse igual."""
		for xmlid in ("classification_rule_localizacion", "classification_rule_interno",
					  "classification_rule_cliente"):
			regla = self.env.ref("primate_repo_manager.%s" % xmlid)
			self.assertTrue(regla.name_prefix, xmlid)

	def test_la_verificacion_se_niega_si_se_separaron(self):
		regla = self.Reglas.search([("classification", "=", "cliente")], limit=1)
		regla.name_prefix = "otracosa-"
		with self.assertRaises(UserError) as capturado:
			self.Reglas.verificar_ida_y_vuelta(
				"cliente", self.Reglas.nombre_para("cliente", "Casmu"))
		self.assertIn("no vuelve a clasificar", str(capturado.exception))

	def test_sin_prefijo_declarado_NO_se_inventa_uno(self):
		"""Un default silencioso que después nadie recuerda haber elegido."""
		with self.assertRaises(UserError):
			self.Reglas.nombre_para("fork_upstream", "algo")

	# ------------------------------------------------------------------
	# El nombre
	# ------------------------------------------------------------------

	def test_normaliza_acentos_y_espacios(self):
		self.assertEqual(
			self.Reglas.nombre_para("cliente", "Mutualista Casmú"), "cliente-mutualista-casmu")

	def test_la_regla_de_cliente_NO_es_un_catch_all(self):
		"""Un repositorio sin la convención sigue quedando sin clasificar, que es el
		hallazgo que corresponde."""
		self.assertFalse(
			self.Reglas.classify({"name": "farmashop", "full_name": "org/farmashop"}))


class TestPlanDeNacimiento(TransactionCase):
	"""B5.2 · el asistente arma un plan; no crea nada."""

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Nacer %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2"})
		# Con App de escritura: el plan de nacimiento arma rulesets, y un ruleset sin la
		# App exenta frenaría la próxima escritura sobre esas ramas. La guarda de B1.1 se
		# niega, y tiene razón — el fixture describía una conexión que no puede gobernar.
		self.backend.write_app_id = "4808079"
		self.valores = {"base": "Mutualista Casmu", "clasificacion": "cliente",
						"version": "19.0", "privado": True}

	def test_el_plan_nace_en_BORRADOR_y_no_escribe_nada(self):
		"""«Revisar el plan y crear», dice el mockup. No «crear»."""
		plan = self.env["repo.write.plan"].armar_nacimiento(self.backend, self.valores)
		self.assertEqual(plan.state, "draft")
		self.assertTrue(plan.operation_ids)

	def test_la_primera_operacion_es_crear_el_repositorio(self):
		plan = self.env["repo.write.plan"].armar_nacimiento(self.backend, self.valores)
		primera = plan.operation_ids.sorted("sequence")[0]
		self.assertEqual(primera.kind, "repository_create")
		self.assertEqual(primera.target, "cliente-mutualista-casmu")

	def test_NO_se_arma_el_plan_si_el_nombre_no_vuelve(self):
		"""La guarda corre ANTES de crear nada: no queda medio plan armado."""
		self.env["repo.classification.rule"].search(
			[("classification", "=", "cliente")], limit=1).name_prefix = "mal-"
		antes = self.env["repo.write.plan"].search_count([])
		with self.assertRaises(UserError):
			self.env["repo.write.plan"].armar_nacimiento(self.backend, self.valores)
		self.assertEqual(self.env["repo.write.plan"].search_count([]), antes)

	# ------------------------------------------------------------------
	# El resumen del paso 3
	# ------------------------------------------------------------------

	def test_el_resumen_dice_QUE_se_va_a_crear_antes_de_crearlo(self):
		resumen = self.env["repo.write.plan"].resumen_de_nacimiento(self.valores)
		self.assertEqual(resumen["nombre"], "cliente-mutualista-casmu")
		self.assertEqual(resumen["ramas"],
						 ["19.0-prod", "19.0-support", "19.0-staging", "19.0-dev"])

	def test_los_ROLES_de_las_ramas_los_decide_la_regla_de_siempre(self):
		"""`19.0-prod` es producción porque la regla lo dice, no porque acá lo supongamos."""
		resumen = self.env["repo.write.plan"].resumen_de_nacimiento(self.valores)
		self.assertIn("19.0-prod", resumen["ramas_gobernadas"])
		self.assertIn("19.0-support", resumen["ramas_gobernadas"])
		self.assertNotIn("19.0-dev", resumen["ramas_gobernadas"])

	def test_el_resumen_dice_que_Dependabot_nace_encendido(self):
		"""Sin esa operación, el repositorio perfecto estrenaría un hallazgo el día uno."""
		self.assertTrue(
			self.env["repo.write.plan"].resumen_de_nacimiento(self.valores)["dependabot"])


class TestAsistenteDeNacimiento(TransactionCase):
	"""B5.3 · los tres pasos, el encadenamiento y lo que el resumen promete."""

	def setUp(self):
		super().setUp()
		self.env.user.group_ids |= self.env.ref("primate_repo_manager.group_repo_lead")
		self.backend = self.env["repo.backend"].create({
			"name": "Asis %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected", "environment": "sandbox"})
		self.backend.write_app_id = "4808079"
		self.responsable = self.env["repo.member"].create({
			"github_login": "mrodriguez", "name": "Martín Rodríguez"})
		# El paso de identidad escribe en la conexión durable, y en un test nada está
		# confirmado: sin este reemplazo la conexión nueva no vería el plan y el test
		# fallaría por la costura, no por lo que prueba. La durabilidad se comprueba
		# contra el sandbox, en dos procesos.
		sin_cursor_aparte(self)

	def _asistente(self, **extra):
		valores = {
			"backend_id": self.backend.id, "base": "Mutualista Casmu",
			"classification": "cliente", "version": "19.0",
			"member_id": self.responsable.id}
		valores.update(extra)
		return self.env["repo.repository.create.wizard"].create(valores)

	# ------------------------------------------------------------------
	# El asistente NO escribe
	# ------------------------------------------------------------------

	def test_el_boton_arma_un_plan_y_no_toca_GitHub(self):
		"""«Revisar el plan y crear», no «Crear». Es la única escritura que crea objetos
		nuevos: dejarla fuera del embudo sería la excepción más cara posible."""
		accion = self._asistente().action_armar_plan()
		plan = self.env["repo.write.plan"].browse(accion["res_id"])
		self.assertEqual(plan.state, "draft")
		self.assertTrue(plan.operation_ids)

	# ------------------------------------------------------------------
	# EL ENCADENAMIENTO
	# ------------------------------------------------------------------

	def _plan(self):
		accion = self._asistente().action_armar_plan()
		return self.env["repo.write.plan"].browse(accion["res_id"])

	def test_las_ramas_dependen_de_la_creacion(self):
		"""Si la creación falla, ninguna se intenta contra un repositorio que no está."""
		plan = self._plan()
		creacion = plan.operation_ids.filtered(
			lambda o: o.kind == "repository_create")
		for rama in plan.operation_ids.filtered(lambda o: o.kind == "branch_create"):
			self.assertIn(creacion, rama.depends_on_ids, rama.target)

	def test_cada_ruleset_depende_de_LAS_RAMAS_QUE_NOMBRA(self):
		"""Un ruleset cuya rama no se creó no protege nada: GitHub lo acepta igual y
		queda «aplicado» sin gobernar."""
		plan = self._plan()
		rulesets = plan.operation_ids.filtered(lambda o: o.kind == "ruleset_create")
		self.assertTrue(rulesets)
		for op in rulesets:
			ramas = op.depends_on_ids.filtered(lambda o: o.kind == "branch_create")
			self.assertTrue(ramas, op.target)
			payload = json.loads(op.payload_json)
			incluidas = payload["conditions"]["ref_name"]["include"]
			for rama in ramas:
				self.assertIn("refs/heads/%s" % rama.target, incluidas)

	def test_el_grant_y_Dependabot_tambien_cuelgan_de_la_creacion(self):
		plan = self._plan()
		creacion = plan.operation_ids.filtered(lambda o: o.kind == "repository_create")
		for kind in ("collaborator_grant", "dependabot_enable"):
			op = plan.operation_ids.filtered(lambda o, k=kind: o.kind == k)
			self.assertTrue(op, kind)
			self.assertIn(creacion, op.depends_on_ids, kind)

	def test_el_orden_es_creacion_ramas_rulesets_grants_dependabot(self):
		plan = self._plan()
		por_orden = plan.operation_ids.sorted("sequence").mapped("kind")
		self.assertEqual(por_orden[0], "repository_create")
		self.assertEqual(por_orden.index("branch_create"), 1)
		self.assertLess(por_orden.index("branch_create"),
						por_orden.index("ruleset_create"))
		self.assertEqual(por_orden[-1], "dependabot_enable")

	# ------------------------------------------------------------------
	# El resumen del paso 3
	# ------------------------------------------------------------------

	def test_el_resumen_cuenta_las_operaciones_que_el_plan_va_a_tener(self):
		"""Prometer nueve y armar siete sería mentir en el único número que alguien
		mira antes de apretar."""
		asistente = self._asistente()
		prometidas = self.env["repo.write.plan"].resumen_de_nacimiento({
			"base": asistente.base, "clasificacion": asistente.classification,
			"version": asistente.version, "privado": asistente.private,
			"responsable": asistente.member_id,
		})["operaciones"]
		plan = self.env["repo.write.plan"].browse(
			asistente.action_armar_plan()["res_id"])
		self.assertEqual(prometidas, len(plan.operation_ids))

	def test_el_resumen_avisa_que_la_creacion_NO_se_deshace(self):
		self.assertIn("no se puede deshacer", self._asistente().resumen_html)

	def test_sin_responsable_lo_dice_en_vez_de_callarlo(self):
		"""Un repositorio sin nadie con administración es un dato, no un detalle."""
		asistente = self._asistente(member_id=False)
		self.assertIn("nadie queda con administración", asistente.resumen_html)

	def test_si_el_nombre_no_puede_armarse_se_dice_MIENTRAS_se_elige(self):
		"""Un asistente que deja apretar y falla después obliga a leer un error para
		entender que faltaba un dato."""
		asistente = self._asistente(classification="fork_upstream")
		self.assertTrue(asistente.problema)
		self.assertFalse(asistente.resumen_html)
		with self.assertRaises(UserError):
			asistente.action_armar_plan()

	# ------------------------------------------------------------------
	# La irreversible, en la aprobación
	# ------------------------------------------------------------------

	def test_la_creacion_NO_se_aprueba_sin_su_confirmacion_propia(self):
		"""Un hueco que este paso destapó: la aprobación exigía confirmar las
		DESTRUCTIVAS, y crear un repositorio no lo es —no le saca nada a nadie— pero no
		tiene vuelta atrás. Hasta B5 ningún tipo implementado era irreversible, así que
		el renglón decía sólo «destructivas» y nadie lo notaba."""
		plan = self._plan()
		creacion = plan.operation_ids.filtered(lambda o: o.kind == "repository_create")
		self.assertTrue(creacion.is_irreversible)
		self.assertFalse(creacion.is_destructive, "no es destructiva: no le quita nada")
		with self.assertRaises(UserError) as capturado:
			plan._aprobar(confirmadas=self.env["repo.write.operation"])
		self.assertIn("sin confirmar", str(capturado.exception))

	def test_con_su_confirmacion_el_plan_se_aprueba(self):
		plan = self._plan()
		exigen = plan.operation_ids.filtered(
			lambda o: o.is_destructive or o.is_irreversible)
		plan._aprobar(confirmadas=exigen)
		self.assertEqual(plan.state, "approved")

	def test_al_crear_el_repositorio_el_resto_del_plan_recibe_su_destino(self):
		"""Cuando el plan se arma el repositorio no existe: las ramas y los rulesets se
		declaran sin `repository_id` porque no hay fila del espejo a la cual apuntar.

		Sin este paso, esas operaciones pedirían `/repos//git/refs` — una URL sin
		repositorio, que GitHub contesta con un 404 que no explica nada. Lo encontré
		revisando el encadenamiento antes del ensayo, no aplicando.
		"""
		plan = self._plan()
		creacion = plan.operation_ids.filtered(lambda o: o.kind == "repository_create")
		self.assertFalse(plan.operation_ids.mapped("repository_id"),
						 "al armar el plan todavía no hay repositorio")

		creacion._id_del_repositorio({
			"id": 4242, "name": "cliente-mutualista-casmu",
			"full_name": "%s/cliente-mutualista-casmu" % self.backend.owner_login,
			"private": True, "default_branch": "main"})

		hermanas = plan.operation_ids - creacion
		self.assertTrue(hermanas.mapped("repository_id"))
		self.assertEqual(
			set(hermanas.mapped("repository_id.full_name")),
			{"%s/cliente-mutualista-casmu" % self.backend.owner_login})

	def test_el_espejo_se_escribe_por_el_MISMO_upsert_que_el_sync(self):
		"""Dos caminos que escriben el mismo objeto divergen, y el día del webhook
		habría tres."""
		import inspect

		from ..models import repo_write_apply
		fuente = inspect.getsource(repo_write_apply.RepoWriteOperationApply._id_del_repositorio)
		self.assertIn('_upsert(', fuente)

	def test_el_espejo_NO_se_escribe_en_la_conexion_durable(self):
		"""Odoo abre sus transacciones en REPEATABLE READ: una fila confirmada por otra
		conexión es INVISIBLE para la transacción en curso.

		Lo intenté al revés —el repositorio existe en GitHub, así que su fila «debería»
		sobrevivir a un rollback— y el apply enlazaba las operaciones a un id que no
		podía leer. Lo que garantiza no perder de vista un repositorio recién creado no
		es la fila del espejo sino la ENTRADA DE IDENTIDAD en la bitácora, que sí es
		durable e inmutable. El espejo es una copia; la bitácora es el registro.
		"""
		import inspect

		from ..models import repo_write_apply
		fuente = inspect.getsource(repo_write_apply.RepoWriteOperationApply._id_del_repositorio)
		self.assertNotIn("_cursor_durable", fuente)

	def test_SIN_responsable_el_numero_prometido_tambien_cierra(self):
		"""El conteo contaba el grant siempre, y sin responsable el plan arma uno menos.

		El test de arriba nunca lo vio porque siempre pasaba un responsable; lo destapó
		el ensayo contra el sandbox corriendo sin él. El número prometido es el único que
		alguien mira antes de apretar.
		"""
		asistente = self._asistente(member_id=False)
		prometidas = self.env["repo.write.plan"].resumen_de_nacimiento({
			"base": asistente.base, "clasificacion": asistente.classification,
			"version": asistente.version, "privado": asistente.private,
			"responsable": asistente.member_id,
		})["operaciones"]
		plan = self.env["repo.write.plan"].browse(
			asistente.action_armar_plan()["res_id"])
		self.assertEqual(prometidas, len(plan.operation_ids))
