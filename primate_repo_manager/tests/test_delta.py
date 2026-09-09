# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""E2.2a · el motor del delta, probado solo.

Lo que se vigila acá no es que sepa restar dos listas —eso es fácil— sino que **no diga
que algo se resolvió cuando nadie lo miró**. Es la afirmación cómoda de este módulo: el
número mejora solo, nadie la revisa, y es exactamente la clase de mentira que la tercera
categoría del mockup existe para impedir.
"""
import uuid

from odoo import fields
from odoo.tests.common import TransactionCase


class TestDelta(TransactionCase):

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Delta %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2",
			"state": "connected"})
		self.repo = self._repo("uno")
		self.otro = self._repo("dos")

	def _repo(self, nombre):
		return self.env["repo.repository"].create({
			"backend_id": self.backend.id,
			"github_id": uuid.uuid4().hex[:8],
			"name": nombre, "full_name": "cuenta/%s" % nombre})

	def _corrida(self, state="done", repos=None, lineas="done"):
		"""Una corrida con su fila por repositorio, como la deja el recorrido real."""
		corrida = self.env["repo.audit.run"].create({
			"name": "C %s" % uuid.uuid4().hex[:4], "backend_id": self.backend.id,
			"state": state, "finished_at": fields.Datetime.now()})
		for repo in (repos if repos is not None else [self.repo, self.otro]):
			self.env["repo.audit.run.line"].create({
				"run_id": corrida.id, "repository_id": repo.id, "state": lineas})
		return corrida

	def _hallazgo(self, corrida, repo=None, tipo="branch_unprotected", sujeto="19.0"):
		return self.env["repo.audit.finding"].create({
			"run_id": corrida.id,
			"repository_id": repo.id if repo else False,
			"finding_type": tipo, "severity": "high",
			"subject": sujeto, "summary": "%s en %s" % (tipo, sujeto)})

	# --- la clave ---

	def test_la_clave_es_lo_que_el_hallazgo_AFIRMA_y_no_su_id(self):
		"""Los hallazgos se borran y se rehacen en cada corrida: comparar por id daría
		«todo nuevo, todo resuelto» todas las semanas."""
		a, b = self._corrida(), self._corrida()
		h1 = self._hallazgo(a, self.repo)
		h2 = self._hallazgo(b, self.repo)
		Delta = self.env["repo.audit.delta"]
		self.assertNotEqual(h1.id, h2.id)
		self.assertEqual(Delta.clave(h1), Delta.clave(h2))

	def test_un_repositorio_RENOMBRADO_no_estrena_todos_sus_hallazgos(self):
		"""La clave lleva el id del espejo, no el nombre. El espejo sigue al repositorio
		por `github_id`, así que un renombre en GitHub no es un repositorio nuevo."""
		antes = self._corrida()
		h = self._hallazgo(antes, self.repo)
		clave_antes = self.env["repo.audit.delta"].clave(h)
		self.repo.full_name = "cuenta/con-otro-nombre"
		ahora = self._corrida()
		h2 = self._hallazgo(ahora, self.repo)

		self.assertEqual(self.env["repo.audit.delta"].clave(h2), clave_antes)
		delta = ahora.delta()
		self.assertFalse(delta["nuevos"])
		self.assertFalse(delta["resueltos"])

	# --- cuál es la anterior ---

	def test_la_anterior_es_la_ultima_TERMINADA_del_mismo_backend(self):
		vieja = self._corrida(state="done")
		nueva = self._corrida(state="done")
		self.assertEqual(nueva.delta()["anterior"], vieja)

	def test_una_corrida_FALLIDA_no_cuenta_como_anterior(self):
		"""Media foto es peor que ninguna: parecería que aparecieron treinta hallazgos
		cuando lo que pasó es que la vez anterior no se llegó a mirar."""
		buena = self._corrida(state="done")
		self._corrida(state="error")
		nueva = self._corrida(state="done")
		self.assertEqual(nueva.delta()["anterior"], buena)

	def test_una_corrida_TERMINADA_CON_ERRORES_si_cuenta_como_anterior(self):
		"""`partial` terminó de recorrer: sabe de cuáles no pudo hablar, y eso alcanza
		para comparar diciendo de cuáles no habla."""
		parcial = self._corrida(state="partial")
		nueva = self._corrida(state="done")
		self.assertEqual(nueva.delta()["anterior"], parcial)

	def test_una_corrida_FALLIDA_no_tiene_delta(self):
		fallida = self._corrida(state="error")
		delta = fallida.delta()
		self.assertFalse(delta["comparable"])
		self.assertIn("incompleta", delta["motivo"])

	def test_la_PRIMERA_corrida_lo_dice_en_vez_de_inventar_un_delta(self):
		delta = self._corrida().delta()
		self.assertFalse(delta["comparable"])
		self.assertIn("primera", delta["motivo"].lower())

	def test_no_se_compara_contra_la_corrida_de_OTRA_conexion(self):
		otro_backend = self.env["repo.backend"].create({
			"name": "Otra", "owner_login": "otra-cuenta", "owner_type": "user",
			"app_id": "1", "installation_id": "9", "state": "connected"})
		self.env["repo.audit.run"].create({
			"name": "Ajena", "backend_id": otro_backend.id, "state": "done"})
		self.assertFalse(self._corrida().delta()["anterior"])

	# --- las tres categorías ---

	def test_lo_que_aparece_es_NUEVO(self):
		antes = self._corrida()
		ahora = self._corrida()
		nuevo = self._hallazgo(ahora, self.repo, sujeto="19.0-prod")
		delta = ahora.delta()
		self.assertEqual(delta["nuevos"], nuevo)
		self.assertFalse(delta["resueltos"])

	def test_lo_que_desaparece_de_un_repo_QUE_SE_RELEYO_es_RESUELTO(self):
		antes = self._corrida()
		ido = self._hallazgo(antes, self.repo)
		ahora = self._corrida()
		delta = ahora.delta()
		self.assertEqual(delta["resueltos"], ido)
		self.assertFalse(delta["sin_confirmar"])

	def test_lo_que_desaparece_de_un_repo_QUE_NO_SE_PUDO_LEER_no_es_resuelto(self):
		"""LA AFIRMACIÓN CÓMODA. El hallazgo no está porque nadie lo miró, y contarlo
		como resuelto mejora el número solo. No cuenta como resuelto ni como nuevo."""
		antes = self._corrida()
		ido = self._hallazgo(antes, self.repo)
		ahora = self._corrida(lineas="error")

		delta = ahora.delta()

		self.assertFalse(delta["resueltos"], "dijo «resuelto» sobre algo que no miró")
		self.assertEqual(delta["sin_confirmar"], ido)
		self.assertIn(self.repo, [r for r, _m in delta["repos_sin_confirmar"]])

	def test_el_repo_sin_confirmar_dice_POR_QUE_no_se_pudo_leer(self):
		antes = self._corrida()
		self._hallazgo(antes, self.repo)
		ahora = self._corrida(repos=[], lineas="done")
		self.env["repo.audit.run.line"].create({
			"run_id": ahora.id, "repository_id": self.repo.id,
			"state": "error", "error": "GitHub 403: Resource not accessible\notra línea"})

		motivos = dict(ahora.delta()["repos_sin_confirmar"])
		self.assertIn("403", motivos[self.repo])

	def test_un_repositorio_AUSENTE_tampoco_confirma_nada(self):
		"""Se sabe que ya no está, no que sus hallazgos se hayan resuelto."""
		antes = self._corrida()
		ido = self._hallazgo(antes, self.repo)
		self.repo.write({"present": False, "absent_since": fields.Datetime.now()})
		ahora = self._corrida(repos=[self.otro])

		delta = ahora.delta()

		self.assertFalse(delta["resueltos"])
		self.assertEqual(delta["sin_confirmar"], ido)
		self.assertIn("listado", dict(delta["repos_sin_confirmar"])[self.repo])

	# --- la salvedad simétrica, del lado de los nuevos ---

	def test_un_nuevo_de_un_repo_QUE_LA_ANTERIOR_NO_MIRO_va_con_su_salvedad(self):
		"""Pudo haber estado ahí todo el tiempo. Se informa igual —esconderlo sería
		peor— pero sin afirmar que es nuevo."""
		antes = self._corrida(state="partial", lineas="error")
		ahora = self._corrida()
		aparecido = self._hallazgo(ahora, self.repo)

		delta = ahora.delta()

		self.assertEqual(delta["nuevos"], aparecido)
		self.assertIn(aparecido.id, delta["sin_base_anterior"])

	def test_un_nuevo_de_un_repo_que_la_anterior_SI_miro_no_lleva_salvedad(self):
		antes = self._corrida()
		ahora = self._corrida()
		aparecido = self._hallazgo(ahora, self.repo)
		self.assertFalse(ahora.delta()["sin_base_anterior"])

	# --- los hallazgos de cuenta, que no tienen repositorio ---

	def test_un_hallazgo_DE_CUENTA_solo_se_da_por_resuelto_si_se_miro_todo(self):
		"""Se calcula sobre todos los repositorios: con uno sin leer, no hay con qué
		afirmar que se resolvió."""
		antes = self._corrida()
		de_cuenta = self._hallazgo(
			antes, None, tipo="convention_adoption", sujeto="")
		ahora = self._corrida(state="partial", lineas="error")

		delta = ahora.delta()

		self.assertFalse(delta["resueltos"])
		self.assertEqual(delta["sin_confirmar"], de_cuenta)

	def test_un_hallazgo_de_cuenta_SI_se_resuelve_cuando_la_corrida_leyo_todo(self):
		antes = self._corrida()
		de_cuenta = self._hallazgo(antes, None, tipo="convention_adoption", sujeto="")
		ahora = self._corrida(state="done")
		self.assertEqual(ahora.delta()["resueltos"], de_cuenta)

	# --- lo que sigue igual no es noticia ---

	def test_lo_que_sigue_no_aparece_en_ninguna_de_las_tres_listas(self):
		antes = self._corrida()
		self._hallazgo(antes, self.repo)
		ahora = self._corrida()
		sigue = self._hallazgo(ahora, self.repo)

		delta = ahora.delta()

		self.assertFalse(delta["nuevos"])
		self.assertFalse(delta["resueltos"])
		self.assertFalse(delta["sin_confirmar"])

	def test_el_delta_NO_usa_run_id_mas_que_para_elegir_los_extremos(self):
		"""El contrato con F4: un hallazgo de webhook no va a pertenecer a una corrida.

		Se comprueba sobre la fuente: la clave de comparación no puede mencionar
		`run_id`. Si algún día lo hiciera, la comparación dejaría de servir para lo que
		este contrato prometió y nadie se enteraría hasta F4.
		"""
		import inspect

		from ..models import repo_audit_delta
		fuente = inspect.getsource(repo_audit_delta.RepoAuditDelta.clave)
		self.assertNotIn("run_id", fuente)
