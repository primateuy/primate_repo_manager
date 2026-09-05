# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""D2.0–D2.2: la barrera, la copia en un commit, y la verificación por hash.

TODO CON TRANSPORTE FALSO. No se toca GitHub: la primera vez que este embudo borre
contenido de verdad va a ser en un ensayo por fases, con Daryl mirando, y esa frontera está
puesta a propósito.

Lo que se prueba acá es lo que no se puede ver mirando: que un borrado NUNCA corra si la
copia no quedó verificada, que la copia sea un solo commit, y que la reversión se niegue si
alguien empujó a la rama en el medio.
"""
import base64
import json
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from .test_backend import RespuestaFalsa, _clave_rsa_de_prueba
from .test_write_apply import sin_cursor_aparte


class TransporteGit:
	"""Un GitHub de mentira que sabe de árboles, blobs, commits y referencias."""

	def __init__(self, arboles, cabezas, mover_la_rama_en_el_medio=False):
		self.arboles = arboles          # {(repo, rama): [(ruta, tipo, sha), ...]}
		self.cabezas = cabezas          # {(repo, rama): sha}
		self.mover = mover_la_rama_en_el_medio
		self.escrituras = []
		self.commits = 0

	def post(self, url, json=None, headers=None, timeout=None, **kw):
		if url.endswith("/access_tokens"):
			return RespuestaFalsa(201, {"token": "ghs_test"})
		self.escrituras.append(("POST", url))
		if "/git/blobs" in url:
			return RespuestaFalsa(201, {"sha": "blob-nuevo"})
		if "/git/trees" in url:
			return RespuestaFalsa(201, {"sha": "arbol-nuevo"})
		if "/git/commits" in url:
			self.commits += 1
			return RespuestaFalsa(201, {"sha": "commit-nuevo"})
		return RespuestaFalsa(201, {})

	def patch(self, url, json=None, headers=None, timeout=None, **kw):
		self.escrituras.append(("PATCH", url))
		return RespuestaFalsa(200, {})

	def delete(self, url, json=None, headers=None, timeout=None, **kw):
		self.escrituras.append(("DELETE", url))
		return RespuestaFalsa(204, {})

	def get(self, url, headers=None, timeout=None, **kw):
		if "/git/ref/heads/" in url:
			repo = url.split("/repos/")[1].split("/git/ref/")[0]
			rama = url.split("/git/ref/heads/")[1]
			return RespuestaFalsa(200, {
				"object": {"sha": self.cabezas.get((repo, rama), "cabeza")}})
		if "/git/trees/" in url:
			repo = url.split("/repos/")[1].split("/git/trees/")[0]
			rama = url.split("/git/trees/")[1].split("?")[0]
			entradas = [{"path": r, "type": t, "sha": s}
						for r, t, s in self.arboles.get((repo, rama), [])]
			return RespuestaFalsa(200, {"tree": entradas, "truncated": False})
		if "/git/blobs/" in url:
			return RespuestaFalsa(200, {
				"content": base64.b64encode(b"print(1)").decode(), "encoding": "base64"})
		if "/installation/repositories" in url:
			return RespuestaFalsa(200, {"repositories": [
				{"full_name": n} for n in self.repos_de_la_instalacion]})
		return RespuestaFalsa(200, {})

	repos_de_la_instalacion = ()


class BaseD2(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "D2 %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected", "environment": "sandbox"})
		self.backend.private_key = self.clave
		self.backend.write_app_id = "10"
		self.backend.write_installation_id = "20"
		self.backend.write_private_key = self.clave

		self.origen = self._repo("cliente-uno")
		self.destino = self._repo("general")
		self.plan = self.env["repo.write.plan"].create({
			"name": "Promoción de mi_modulo", "backend_id": self.backend.id})
		self.env.user.group_ids = [(4, self.env.ref(
			"primate_repo_manager.group_repo_lead").id)]
		sin_cursor_aparte(self)

	def _repo(self, nombre):
		repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "name": nombre,
			"full_name": "%s/%s" % (self.backend.owner_login, nombre),
			"github_id": uuid.uuid4().hex[:8]})
		self.env["repo.branch"].create({
			"repository_id": repo.id, "name": "17.0", "role": "base"})
		return repo

	def _copia(self, arbol_esperado="ARBOL-DEL-MODULO"):
		return self.env["repo.write.operation"].create({
			"plan_id": self.plan.id, "kind": "module_copy", "sequence": 10,
			"repository_id": self.destino.id, "target": "addons/mi_modulo",
			"payload_json": json.dumps({
				"origen_repo": self.origen.full_name, "origen_rama": "17.0",
				"ruta": "addons/mi_modulo", "modulo": "mi_modulo",
				"destino_rama": "17.0", "arbol_esperado": arbol_esperado}),
		})

	def _transporte(self, sha_en_destino="ARBOL-DEL-MODULO"):
		arboles = {
			(self.origen.full_name, "17.0"): [
				("addons/mi_modulo", "tree", "ARBOL-DEL-MODULO"),
				("addons/mi_modulo/__manifest__.py", "blob", "b1"),
				("addons/mi_modulo/models.py", "blob", "b2")],
			(self.destino.full_name, "17.0"): (
				[("addons/mi_modulo", "tree", sha_en_destino)] if sha_en_destino else []),
		}
		t = TransporteGit(arboles, {
			(self.origen.full_name, "17.0"): "c-origen",
			(self.destino.full_name, "17.0"): "c-destino"})
		t.repos_de_la_instalacion = (self.origen.full_name, self.destino.full_name)
		return t

	def _aplicar(self, transporte):
		Backend = type(self.backend)
		original = Backend.write_client
		Backend.write_client = lambda s, transport=None: original(s, transport=transporte)
		try:
			self.plan.action_apply()
		finally:
			Backend.write_client = original


class TestLaBarrera(BaseD2):
	"""D2.0. Lo más importante de todo D2: sin esto nada de lo demás es seguro."""

	def test_una_operacion_con_dependencia_incumplida_NO_se_ejecuta(self):
		"""EL test. Si la copia falla, el borrado no puede correr — el peor caso permitido
		es duplicación benigna, nunca borrado sin copia.

		MUTACIÓN OBLIGATORIA: sacando el chequeo de `_dependencias_incumplidas` del bucle
		del apply, este test se pone rojo.
		"""
		copia = self._copia()
		segunda = self.env["repo.write.operation"].create({
			"plan_id": self.plan.id, "kind": "collaborator_revoke", "sequence": 20,
			"repository_id": self.origen.id, "target": "alguien",
			"depends_on_ids": [(6, 0, copia.ids)]})
		# La copia va a fallar: el destino queda con otro hash.
		self._aprobar()
		self._aplicar(self._transporte(sha_en_destino="OTRA-COSA"))

		self.assertEqual(copia.state, "failed")
		self.assertEqual(segunda.state, "blocked_by_dependency")
		self.assertIn("mi_modulo", segunda.dependency_blocked_by or "")

	def test_bloqueada_por_dependencia_NO_es_lo_mismo_que_fallida(self):
		"""Marcarla como fallida mandaría a alguien a buscar un error de GitHub que no
		existe. Lo que pasó es que ni se intentó."""
		copia = self._copia()
		segunda = self.env["repo.write.operation"].create({
			"plan_id": self.plan.id, "kind": "collaborator_revoke", "sequence": 20,
			"repository_id": self.origen.id, "target": "alguien",
			"depends_on_ids": [(6, 0, copia.ids)]})
		self._aprobar()
		t = self._transporte(sha_en_destino="OTRA-COSA")
		self._aplicar(t)
		self.assertNotEqual(segunda.state, "failed")
		self.assertFalse(segunda.error, "no hay error porque no hubo intento")
		# Y NO salió una sola escritura por la operación bloqueada.
		self.assertFalse([e for e in t.escrituras if "alguien" in e[1]])

	def test_con_la_dependencia_cumplida_la_segunda_SI_corre(self):
		copia = self._copia()
		segunda = self.env["repo.write.operation"].create({
			"plan_id": self.plan.id, "kind": "collaborator_revoke", "sequence": 20,
			"repository_id": self.origen.id, "target": "alguien",
			"depends_on_ids": [(6, 0, copia.ids)]})
		self._aprobar()
		self._aplicar(self._transporte())
		self.assertEqual(copia.state, "applied")
		self.assertNotEqual(segunda.state, "blocked_by_dependency")

	def test_un_plan_con_algo_bloqueado_queda_FALLIDO(self):
		"""Algo que se aprobó no se hizo. Que no se haya intentado es la razón, no una
		atenuante."""
		copia = self._copia()
		self.env["repo.write.operation"].create({
			"plan_id": self.plan.id, "kind": "collaborator_revoke", "sequence": 20,
			"repository_id": self.origen.id, "target": "alguien",
			"depends_on_ids": [(6, 0, copia.ids)]})
		self._aprobar()
		self._aplicar(self._transporte(sha_en_destino="OTRA-COSA"))
		self.assertEqual(self.plan.state, "failed")

	def test_las_dependencias_entran_en_la_huella(self):
		"""Cambiar de qué depende una operación cambia EN QUÉ CONDICIONES se ejecuta, que
		es tan parte de lo aprobado como el payload."""
		copia = self._copia()
		otra = self.env["repo.write.operation"].create({
			"plan_id": self.plan.id, "kind": "collaborator_revoke", "sequence": 20,
			"repository_id": self.origen.id, "target": "alguien"})
		huella = self.plan._huella()
		otra.depends_on_ids = [(6, 0, copia.ids)]
		self.plan.invalidate_recordset()
		self.assertNotEqual(self.plan._huella(), huella)

	def _aprobar(self):
		self.plan._aprobar(
			confirmadas=self.plan.operation_ids.filtered("is_destructive"))


class TestCopiaEnUnCommit(BaseD2):
	"""D2.1 y D2.2."""

	def _aprobar(self):
		self.plan._aprobar(
			confirmadas=self.plan.operation_ids.filtered("is_destructive"))

	def test_la_copia_es_UN_solo_commit(self):
		"""Cuarenta archivos con la API de contenidos serían cuarenta commits, y una
		interrupción en el medio dejaría un módulo a la mitad."""
		self._copia()
		self._aprobar()
		t = self._transporte()
		self._aplicar(t)
		self.assertEqual(t.commits, 1)

	def test_la_referencia_se_mueve_SIN_force(self):
		"""Perder nuestro commit es molesto; pisar el de otro es inaceptable.

		MUTACIÓN: poner `force: True` en el PATCH del apply y este test avisa.
		"""
		import inspect

		from ..models import repo_write_module

		fuente = inspect.getsource(
			repo_write_module.RepoWriteOperationModule._copiar_modulo)
		self.assertIn('"force": False', fuente)

	def test_la_verificacion_compara_HASHES_y_no_confia_en_la_API(self):
		self._copia()
		self._aprobar()
		self._aplicar(self._transporte())
		self.assertEqual(self.plan.operation_ids.state, "applied")

	def test_si_la_copia_no_queda_IDENTICA_la_operacion_falla(self):
		"""Es la condición que después abre la barrera de los borrados: tiene que ser
		certeza, no «parece que sí»."""
		self._copia()
		self._aprobar()
		self._aplicar(self._transporte(sha_en_destino="DISTINTO"))
		op = self.plan.operation_ids
		self.assertEqual(op.state, "failed")
		self.assertIn("NO quedó idéntica", op.error or "")

	def test_copiar_cero_archivos_es_un_error_y_no_un_commit_vacio(self):
		"""Un commit vacío después parecería una copia hecha."""
		self._copia()
		self._aprobar()
		t = self._transporte()
		t.arboles[(self.origen.full_name, "17.0")] = [("otra/cosa", "blob", "x")]
		self._aplicar(t)
		self.assertEqual(self.plan.operation_ids.state, "failed")
		self.assertIn("cero archivos", self.plan.operation_ids.error or "")

	def test_un_arbol_truncado_NO_se_copia_a_ciegas(self):
		self._copia()
		self._aprobar()
		t = self._transporte()
		original = t.get

		def truncado(url, **kw):
			r = original(url, **kw)
			if "/git/trees/" in url:
				r.json()["truncated"] = True
			return r

		t.get = truncado
		self._aplicar(t)
		self.assertEqual(self.plan.operation_ids.state, "failed")

	# --- la reversión, con condición de avance rápido -----------------------

	def test_revertir_se_NIEGA_si_la_rama_se_movio(self):
		"""Un rollback que destruye el trabajo de otro es peor que no revertir.

		MUTACIÓN: quitar la comparación de la cabeza y este test se pone rojo.
		"""
		self._copia()
		self._aprobar()
		t = self._transporte()
		self._aplicar(t)
		op = self.plan.operation_ids
		self.assertEqual(op.state, "applied")

		# Alguien empujó después de nuestra copia.
		t.cabezas[(self.destino.full_name, "17.0")] = "commit-de-otro"
		Backend = type(self.backend)
		original = Backend.write_client
		Backend.write_client = lambda s, transport=None: original(s, transport=t)
		try:
			with self.assertRaises(UserError) as ctx:
				op.action_rollback_operation()
		finally:
			Backend.write_client = original
		self.assertIn("se movió después de la copia", str(ctx.exception))
		self.assertEqual(op.state, "applied", "no se revirtió, y está bien")


class TestGuardaDeRamaProtegida(BaseD2):
	"""La rama de destino que exige PR se detecta AL ARMAR, no al aplicar."""

	def test_un_destino_que_exige_PR_no_deja_aprobar_el_plan(self):
		self._copia()
		rama = self.destino.branch_ids[0]
		rama.write({
			"protected": True,
			"protection_json": json.dumps({
				"required_pull_request_reviews": {
					"required_approving_review_count": 1}}),
		})
		with self.assertRaises(UserError) as ctx:
			self.plan._aprobar()
		self.assertIn("exige pull request", str(ctx.exception))
		self.assertEqual(self.plan.state, "draft")

	def test_y_el_mensaje_dice_cual_es_la_salida_definitiva(self):
		"""Sin esa exención, la gobernanza que B instala estrangularía a D2."""
		self._copia()
		self.destino.branch_ids[0].write({
			"protected": True,
			"protection_json": json.dumps({
				"required_pull_request_reviews": {}}),
		})
		with self.assertRaises(UserError) as ctx:
			self.plan._aprobar()
		self.assertIn("excepción", str(ctx.exception))

	def test_un_destino_sin_proteccion_se_aprueba_normal(self):
		self._copia()
		self.plan._aprobar()
		self.assertEqual(self.plan.state, "approved")
