# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Hallazgos con la bandeja del plan — página 2c, y el gesto según la 6d.

Lo que se prueba acá es la puerta del servidor: que arrastrar y hacer clic entren por el
MISMO lugar, que ninguna de las dos escriba en GitHub, y que lo rechazado vuelva con su
causa concreta. Que se dibuje y que el teclado llegue hasta el final lo prueba el tour.
"""
import uuid

from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase

from .test_backend import _clave_rsa_de_prueba


class BaseHallazgos(TransactionCase):

	def setUp(self):
		super().setUp()
		self.env.user.group_ids |= self.env.ref("primate_repo_manager.group_repo_lead")
		self.backend = self.env["repo.backend"].create({
			"name": "Hallazgos %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"environment": "sandbox"})
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx", "full_name": "org/sbx"})
		self.corrida = self.env["repo.audit.run"].create({
			"name": "Corrida", "backend_id": self.backend.id, "state": "done"})

	def _hallazgo(self, tipo="permission_exceeded", sujeto="alguien", payload=None):
		return self.env["repo.audit.finding"].build(
			self.corrida, tipo, "algo", repository=self.repo, severity="high",
			subject=sujeto, remediation_payload=payload or {"permission": "pull"})


class TestLaVistaPreviaDeLaOperacion(BaseHallazgos):
	"""Lo que la columna «Se propone» muestra."""

	def test_la_frase_es_LA_MISMA_que_va_a_tener_la_operación(self):
		"""Se le pregunta a la operación en vez de redactar una versión parecida: dos
		redacciones del mismo hecho envejecen distinto, y alguien leería una cosa antes de
		planificar y otra después."""
		hallazgo = self._hallazgo()
		previa = hallazgo.operations_preview
		self.assertTrue(previa)
		hallazgo.action_remediate()
		self.assertEqual(hallazgo.planned_operation_id.description, previa)

	def test_la_vista_previa_no_crea_nada(self):
		"""Se arma en memoria. Si tocara la base, mirar una lista dejaría operaciones."""
		antes = self.env["repo.write.operation"].search_count([])
		hallazgo = self._hallazgo()
		hallazgo.operations_preview  # noqa: B018 — el compute es el que importa
		self.assertEqual(self.env["repo.write.operation"].search_count([]), antes)

	def test_un_hallazgo_que_no_se_remedia_no_promete_ninguna_operación(self):
		hallazgo = self._hallazgo(
			tipo="branch_unprotected", payload={"repository": "org/sbx", "branch": "17.0"})
		self.assertFalse(hallazgo.can_be_planned)
		self.assertFalse(hallazgo.operations_preview)


class TestLaPuertaDeLaBandeja(BaseHallazgos):
	"""`agregar_al_borrador` es lo que hacen el arrastre Y el enlace. La misma."""

	def test_agrega_al_borrador_y_lo_dice(self):
		hallazgo = self._hallazgo()
		resultado = hallazgo.agregar_al_borrador()
		self.assertEqual(resultado["agregadas"], 1)
		self.assertTrue(resultado["plan_id"])
		self.assertTrue(hallazgo.planned_operation_id)

	def test_el_plan_queda_en_BORRADOR_y_nada_se_escribió(self):
		"""Ningún arrastre escribe en GitHub: arma un plan y se detiene ahí."""
		hallazgo = self._hallazgo()
		hallazgo.agregar_al_borrador()
		self.assertEqual(hallazgo.planned_plan_id.state, "draft")
		self.assertFalse(hallazgo.planned_operation_id.approved)

	def test_dos_hallazgos_van_al_MISMO_borrador(self):
		uno, otro = self._hallazgo(sujeto="uno"), self._hallazgo(sujeto="otro")
		(uno | otro).agregar_al_borrador()
		self.assertEqual(uno.planned_plan_id, otro.planned_plan_id)

	def test_lo_rechazado_vuelve_CON_SU_CAUSA(self):
		"""«Acción no permitida» manda a adivinar; la causa concreta se puede resolver."""
		sin_camino = self._hallazgo(
			tipo="branch_unprotected", payload={"repository": "org/sbx", "branch": "17.0"})
		resultado = sin_camino.agregar_al_borrador()
		self.assertEqual(resultado["agregadas"], 0)
		self.assertEqual(len(resultado["rechazados"]), 1)
		self.assertIn("plantilla de política", resultado["rechazados"][0])

	def test_uno_que_no_aplica_NO_tumba_al_lote(self):
		"""Un lote que se niega entero porque uno de veinte no aplicaba obliga a
		seleccionar de a uno, que es lo que el gesto viene a evitar."""
		bueno = self._hallazgo(sujeto="bueno")
		malo = self._hallazgo(
			tipo="branch_unprotected", payload={"repository": "org/sbx", "branch": "17.0"})
		resultado = (bueno | malo).agregar_al_borrador()
		self.assertEqual(resultado["agregadas"], 1)
		self.assertEqual(len(resultado["rechazados"]), 1)

	def test_el_que_ya_está_en_un_plan_se_rechaza_diciendo_en_cuál(self):
		hallazgo = self._hallazgo()
		hallazgo.agregar_al_borrador()
		resultado = hallazgo.agregar_al_borrador()
		self.assertEqual(resultado["agregadas"], 0)
		self.assertIn("ya está en el plan", resultado["rechazados"][0])


class TestLaBandejaQueLaPantallaLee(BaseHallazgos):

	def test_sin_borrador_la_bandeja_viene_vacía_y_no_inventa_un_plan(self):
		datos = self.env["repo.write.plan"].bandeja_del_borrador(self.backend.id)
		self.assertFalse(datos["plan"])
		self.assertEqual(datos["operaciones"], [])

	def test_la_bandeja_trae_la_frase_la_etiqueta_y_si_saca_algo(self):
		hallazgo = self._hallazgo()
		hallazgo.agregar_al_borrador()
		datos = self.env["repo.write.plan"].bandeja_del_borrador(self.backend.id)
		self.assertTrue(datos["plan"])
		operacion = datos["operaciones"][0]
		self.assertTrue(operacion["descripcion"])
		self.assertTrue(operacion["destructiva"])
		# La ETIQUETA, no el valor: el chip mostraba «HIGH» crudo.
		self.assertEqual(operacion["severidad_label"], "Alto")


@tagged("post_install", "-at_install")
class TestTourHallazgos(HttpCase):

	def setUp(self):
		super().setUp()
		clave = _clave_rsa_de_prueba()
		backend = self.env["repo.backend"].create({
			"name": "GitHub — tour hallazgos",
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected", "environment": "sandbox"})
		backend.private_key = clave
		repo = self.env["repo.repository"].create({
			"backend_id": backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx-tour", "full_name": "cuenta/sbx-tour"})
		corrida = self.env["repo.audit.run"].create({
			"name": "Corrida del tour", "backend_id": backend.id, "state": "done"})
		Finding = self.env["repo.audit.finding"]
		# Uno que se puede remediar y uno que no: el tour necesita las dos formas.
		Finding.build(corrida, "permission_exceeded", "alguien tiene de más",
					  repository=repo, severity="high", subject="alguien",
					  remediation_payload={"permission": "pull"})
		Finding.build(corrida, "branch_unprotected", "la rama no tiene protección",
					  repository=repo, severity="critical", subject="17.0",
					  remediation_payload={"repository": repo.full_name,
										   "branch": "17.0"})
		self.env.ref("base.user_admin").write({
			"active": True, "password": "admin",
			"group_ids": [
				(4, self.env.ref("primate_repo_manager.group_repo_admin").id),
				(4, self.env.ref("primate_repo_manager.group_repo_lead").id),
				(4, self.env.ref("primate_repo_manager.group_repo_reader").id)]})

	def test_la_pantalla_se_dibuja_y_el_teclado_arma_el_plan(self):
		self.start_tour(
			"/odoo/action-primate_repo_manager.action_repo_audit_finding",
			"prm_hallazgos", login="admin")
