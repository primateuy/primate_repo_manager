# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""E4.4 · los dos avisos permanentes de la barra y las dos puertas de entrada."""
import uuid

from odoo import fields
from odoo.tests.common import TransactionCase


class BaseBarra(TransactionCase):

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Barra %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2",
			"state": "connected"})
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "uno", "full_name": "cuenta/uno"})
		self.env.user.group_ids |= self.env.ref(
			"primate_repo_manager.group_repo_lead")

	def _avisos(self, usuario=None):
		modelo = self.env["repo.audit.run"]
		if usuario:
			modelo = modelo.with_user(usuario)
		return modelo.avisos_de_barra()


class TestLosDosAvisos(BaseBarra):

	def test_sin_nada_pasando_la_barra_esta_CALLADA(self):
		"""Un aviso permanente que aparece seguido deja de leerse, y el día que aparezca
		el que importa va a estar tapado por la costumbre."""
		avisos = self._avisos()
		self.assertFalse(avisos["auditoria"])
		self.assertFalse(avisos["plan"])

	def test_una_auditoria_en_curso_avisa_CON_SU_CONTEO(self):
		"""No es «hay trabajo corriendo»: es «lo que estás mirando no es de ahora». Por
		eso lleva el conteo y no sólo el estado."""
		corrida = self.env["repo.audit.run"].create({
			"name": "En curso", "backend_id": self.backend.id, "state": "running"})
		self.env["repo.audit.run.line"].create({
			"run_id": corrida.id, "repository_id": self.repo.id, "state": "done"})

		aviso = self._avisos()["auditoria"]

		self.assertEqual(aviso["id"], corrida.id)
		self.assertEqual((aviso["leidos"], aviso["total"]), (1, 1))

	def test_una_auditoria_TERMINADA_no_avisa(self):
		self.env["repo.audit.run"].create({
			"name": "Terminada", "backend_id": self.backend.id, "state": "done",
			"finished_at": fields.Datetime.now()})
		self.assertFalse(self._avisos()["auditoria"])

	def test_un_plan_en_borrador_CON_operaciones_avisa(self):
		plan = self.env["repo.write.plan"].create(
			{"name": "P", "backend_id": self.backend.id})
		self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": "collaborator_revoke",
			"repository_id": self.repo.id, "target": "quien", "payload_json": "{}"})

		aviso = self._avisos()["plan"]

		self.assertEqual(aviso["id"], plan.id)
		self.assertEqual(aviso["operaciones"], 1)

	def test_un_plan_VACIO_no_avisa(self):
		"""Un plan sin operaciones no espera nada: avisarlo sería mandar a alguien a
		mirar una pantalla en blanco."""
		self.env["repo.write.plan"].create(
			{"name": "Vacío", "backend_id": self.backend.id})
		self.assertFalse(self._avisos()["plan"])

	def test_a_quien_NO_puede_aprobar_no_se_le_avisa_del_plan(self):
		"""Un aviso permanente sobre algo que uno no puede resolver es ruido que además
		no se puede sacar: lo vería para siempre."""
		plan = self.env["repo.write.plan"].create(
			{"name": "P", "backend_id": self.backend.id})
		self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": "collaborator_revoke",
			"repository_id": self.repo.id, "target": "quien", "payload_json": "{}"})
		lector = self.env["res.users"].create({
			"name": "Sólo mira", "login": "lector-%s" % uuid.uuid4().hex[:8],
			"group_ids": [(4, self.env.ref("base.group_user").id),
						  (4, self.env.ref(
							  "primate_repo_manager.group_repo_reader").id)]})

		self.assertFalse(self._avisos(lector)["plan"])

	def test_la_barra_NO_usa_permisos_elevados(self):
		"""Está en TODAS las pantallas: no puede ser la rendija por la que alguien se
		entera de que existe una conexión que no tiene permiso de mirar.

		Se mira el CÓDIGO y no el texto. La primera versión buscaba «sudo(» en la fuente
		y encontraba el del propio docstring —el que explica que no hay sudo—, así que
		daba rojo con el código correcto. Un test que lee prosa mide la prosa.
		"""
		import ast
		import inspect
		import textwrap

		from ..models import repo_audit_run
		arbol = ast.parse(textwrap.dedent(
			inspect.getsource(repo_audit_run.RepoAuditRun.avisos_de_barra)))
		elevaciones = [
			nodo for nodo in ast.walk(arbol)
			if isinstance(nodo, ast.Attribute) and nodo.attr == "sudo"]
		self.assertFalse(elevaciones, "la barra eleva permisos")


class TestLasDosPuertas(BaseBarra):

	def _usuario(self, grupo):
		return self.env["res.users"].create({
			"name": "Quien", "login": "u-%s" % uuid.uuid4().hex[:8],
			"group_ids": [(4, self.env.ref("base.group_user").id),
						  (4, self.env.ref(grupo).id)]})

	def test_quien_OPERA_aterriza_en_hallazgos(self):
		usuario = self._usuario("primate_repo_manager.group_repo_lead")
		self.assertEqual(
			usuario.action_id.id,
			self.env.ref("primate_repo_manager.action_repo_audit_finding").id)

	def test_quien_solo_MIRA_aterriza_en_el_panel(self):
		"""Abre para saber si mejoramos o empeoramos, no para arreglar."""
		usuario = self._usuario("primate_repo_manager.group_repo_reader")
		self.assertEqual(
			usuario.action_id.id,
			self.env.ref("primate_repo_manager.action_repo_panel_salud").id)

	def test_darle_el_rol_a_alguien_que_YA_EXISTIA_tambien_le_pone_su_puerta(self):
		"""Es como pasa en la práctica: los usuarios no se crean con el rol puesto."""
		usuario = self.env["res.users"].create({
			"name": "Después", "login": "u-%s" % uuid.uuid4().hex[:8],
			"group_ids": [(4, self.env.ref("base.group_user").id)]})
		self.assertFalse(usuario.action_id)

		usuario.group_ids |= self.env.ref("primate_repo_manager.group_repo_reader")

		self.assertEqual(
			usuario.action_id.id,
			self.env.ref("primate_repo_manager.action_repo_panel_salud").id)

	def test_NO_se_pisa_la_puerta_que_alguien_ya_eligio(self):
		"""Un default que sobrescribe lo que alguien configuró deja de ser un default."""
		propia = self.env.ref("primate_repo_manager.action_repo_backend")
		usuario = self.env["res.users"].create({
			"name": "Con la suya", "login": "u-%s" % uuid.uuid4().hex[:8],
			"action_id": propia.id,
			"group_ids": [(4, self.env.ref("base.group_user").id),
						  (4, self.env.ref(
							  "primate_repo_manager.group_repo_reader").id)]})
		self.assertEqual(usuario.action_id.id, propia.id)

	def test_un_usuario_SIN_rol_del_modulo_no_recibe_ninguna_puerta(self):
		usuario = self.env["res.users"].create({
			"name": "Ajeno", "login": "u-%s" % uuid.uuid4().hex[:8],
			"group_ids": [(4, self.env.ref("base.group_user").id)]})
		self.assertFalse(usuario.action_id)
