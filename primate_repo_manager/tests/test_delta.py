# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""E2.2a · el motor del delta, probado solo.

Lo que se vigila acá no es que sepa restar dos listas —eso es fácil— sino que **no diga
que algo se resolvió cuando nadie lo miró**. Es la afirmación cómoda de este módulo: el
número mejora solo, nadie la revisa, y es exactamente la clase de mentira que la tercera
categoría del mockup existe para impedir.
"""
import uuid
from datetime import datetime

from odoo import fields
from odoo.tests import HttpCase, tagged
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


@tagged("post_install", "-at_install")
class TestTourDelta(HttpCase):
	"""La pantalla del delta, en un navegador de verdad.

	Se siembra a mano lo que la corrida dejaría: dos corridas, un hallazgo que sigue, uno
	que aparece, uno que se resuelve, y un repositorio que esta vez no se pudo leer. Es
	la única forma de que el tercer bloque tenga qué dibujar.
	"""

	def setUp(self):
		super().setUp()
		backend = self.env["repo.backend"].create({
			"name": "GitHub — tour delta",
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected", "environment": "sandbox"})
		vivo = self.env["repo.repository"].create({
			"backend_id": backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx-vivo", "full_name": "cuenta/sbx-vivo"})
		caido = self.env["repo.repository"].create({
			"backend_id": backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx-caido", "full_name": "cuenta/sbx-caido"})
		Run = self.env["repo.audit.run"]
		Line = self.env["repo.audit.run.line"]
		Finding = self.env["repo.audit.finding"]

		anterior = Run.create({
			"name": "Auditoría anterior", "backend_id": backend.id, "state": "done",
			"finished_at": fields.Datetime.now()})
		for repo in (vivo, caido):
			Line.create({"run_id": anterior.id, "repository_id": repo.id,
						 "state": "done"})
		# Uno que se va a resolver, y uno que se va a quedar sin confirmar.
		Finding.build(anterior, "permission_exceeded", "alguien tenía de más",
					  repository=vivo, severity="high", subject="alguien",
					  remediation_payload={"permission": "pull"})
		Finding.build(anterior, "branch_unprotected", "la rama del caído",
					  repository=caido, severity="high", subject="17.0")

		self.corrida = Run.create({
			"name": "Auditoría de hoy", "backend_id": backend.id, "state": "partial",
			"finished_at": fields.Datetime.now()})
		Line.create({"run_id": self.corrida.id, "repository_id": vivo.id,
					 "state": "done"})
		Line.create({"run_id": self.corrida.id, "repository_id": caido.id,
					 "state": "error",
					 "error": "GitHub 403: Resource not accessible by integration"})
		# DOS NUEVOS, Y UNO SOLO SE PUEDE PLANIFICAR. Es la mezcla real: el botón tiene
		# que armar el plan con el que se puede y saltear el otro sin negarse entero.
		# `branch_unprotected` NO es planificable a propósito —su payload identifica, no
		# configura, y F1 lo aprendió a los golpes— así que sembrarlo como único nuevo
		# hacía que el botón se negara. El tour lo cazó: la semilla estaba mal, no el
		# selector.
		Finding.build(self.corrida, "branch_unprotected", "la rama quedó sin protección",
					  repository=vivo, severity="critical", subject="19.0",
					  remediation_payload={"repository": vivo.full_name,
										   "branch": "19.0"})
		Finding.build(self.corrida, "permission_exceeded", "otro tiene de más",
					  repository=vivo, severity="high", subject="otro",
					  remediation_payload={"repository": vivo.full_name,
										   "login": "otro", "permission": "pull"})

	def test_la_pantalla_del_delta_dibuja_sus_tres_bloques(self):
		self.start_tour(
			"/odoo/action-primate_repo_manager.action_repo_audit_run/%s" % self.corrida.id,
			"prm_delta", login="admin")


class TestAtribucionDelResuelto(TransactionCase):
	"""E2.2c · por qué dejó de estar. Tres categorías, y ninguna se supone.

	La atribución es una AFIRMACIÓN sobre lo que pasó fuera de esta pantalla, y las tres
	frases se leen distinto: «lo corrigió PLAN-12» es un mérito del equipo, «se resolvió
	fuera de la app» es un aviso de que alguien tocó GitHub por su cuenta. Decir una por
	la otra desinforma en la dirección exacta en la que este módulo no puede desinformar.
	"""

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Atrib %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2",
			"state": "connected"})
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "uno", "full_name": "cuenta/uno"})
		self.Delta = self.env["repo.audit.delta"]

	def _corrida(self, cuando=None, state="done"):
		corrida = self.env["repo.audit.run"].create({
			"name": "C %s" % uuid.uuid4().hex[:4], "backend_id": self.backend.id,
			"state": state, "finished_at": cuando or fields.Datetime.now()})
		self.env["repo.audit.run.line"].create({
			"run_id": corrida.id, "repository_id": self.repo.id, "state": "done"})
		return corrida

	def _hallazgo(self, corrida, tipo="permission_exceeded", sujeto="alguien", repo=True):
		return self.env["repo.audit.finding"].create({
			"run_id": corrida.id,
			"repository_id": self.repo.id if repo else False,
			"finding_type": tipo, "severity": "high", "subject": sujeto,
			"summary": "%s / %s" % (tipo, sujeto)})

	def _plan_aplicado(self, hallazgo, cuando, revertido=False):
		"""Un plan aplicado POR EL CAMINO REAL de la bitácora, no una entrada a mano.

		La entrada `write_applied` es lo que el apply escribe después de releer y
		verificar; fabricarla con otros datos probaría lo que el código debería hacer en
		vez de lo que hace.
		"""
		plan = self.env["repo.write.plan"].create({
			"name": "PLAN de prueba", "backend_id": self.backend.id})
		operacion = self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": "collaborator_revoke", "sequence": 10,
			"repository_id": self.repo.id, "target": hallazgo.subject,
			"finding_id": hallazgo.id, "payload_json": "{}"})
		entrada = self.env["repo.audit.log"].sudo().create({
			"event_type": "write_applied", "backend_id": self.backend.id,
			"repository_id": self.repo.id, "operation_id": operacion.id,
			"summary": "se aplicó", "timestamp": cuando})
		if revertido:
			self.env["repo.audit.log"].sudo().create({
				"event_type": "write_rolled_back", "backend_id": self.backend.id,
				"repository_id": self.repo.id, "operation_id": operacion.id,
				"summary": "se revirtió", "timestamp": cuando})
		return plan, entrada

	# --- 1 · el plan ---

	def test_un_plan_aplicado_en_la_ventana_se_atribuye_CON_SU_NOMBRE(self):
		anterior = self._corrida(cuando=datetime(2026, 9, 1, 10, 0))
		ido = self._hallazgo(anterior)
		plan, _e = self._plan_aplicado(ido, datetime(2026, 9, 3, 12, 0))
		ahora = self._corrida(cuando=datetime(2026, 9, 8, 10, 0))

		atribucion = self.Delta.atribucion(ido, ahora, anterior)

		self.assertEqual(atribucion["categoria"], "plan")
		self.assertIn(plan.display_name, atribucion["texto"])
		self.assertIn("verificado", atribucion["texto"])

	def test_un_plan_aplicado_ANTES_de_la_ventana_no_explica_este_delta(self):
		"""Ya estaba reflejado en lo que la corrida anterior vio: atribuirlo sería
		contarlo dos veces, y encima taparía lo que sí pasó esta semana."""
		anterior = self._corrida(cuando=datetime(2026, 9, 5, 10, 0))
		ido = self._hallazgo(anterior)
		self._plan_aplicado(ido, datetime(2026, 9, 1, 12, 0))
		ahora = self._corrida(cuando=datetime(2026, 9, 8, 10, 0))

		self.assertEqual(
			self.Delta.atribucion(ido, ahora, anterior)["categoria"], "fuera")

	def test_una_escritura_REVERTIDA_no_corrige_nada(self):
		"""Lo que se aplicó se deshizo. Si el hallazgo igual desapareció, fue por otra
		cosa, y decir «lo corrigió PLAN-X» sería falso en los dos sentidos."""
		anterior = self._corrida(cuando=datetime(2026, 9, 1, 10, 0))
		ido = self._hallazgo(anterior)
		self._plan_aplicado(ido, datetime(2026, 9, 3, 12, 0), revertido=True)
		ahora = self._corrida(cuando=datetime(2026, 9, 8, 10, 0))

		self.assertEqual(
			self.Delta.atribucion(ido, ahora, anterior)["categoria"], "fuera")

	# --- 2 · el acto en la app ---

	def test_una_clasificacion_definida_es_un_acto_EN_la_app(self):
		"""Clasificar no escribe en GitHub: no hay plan que lo registre. Decir «se
		resolvió fuera de la app» sería exactamente al revés de lo que pasó."""
		anterior = self._corrida()
		ido = self._hallazgo(anterior, tipo="classification_missing", sujeto="")
		self.repo.classification = "cliente"
		ahora = self._corrida()

		atribucion = self.Delta.atribucion(ido, ahora, anterior)

		self.assertEqual(atribucion["categoria"], "app")
		self.assertIn("clasificación definida", atribucion["texto"])

	def test_una_cuenta_vinculada_tambien(self):
		persona = self.env["repo.member"].create({"github_login": "pepe-%s" % uuid.uuid4().hex[:4]})
		anterior = self._corrida()
		ido = self._hallazgo(anterior, tipo="member_without_employee",
							 sujeto=persona.github_login, repo=False)
		empleado = self.env["hr.employee"].create({"name": "Pepe"})
		persona.employee_id = empleado
		ahora = self._corrida()

		atribucion = self.Delta.atribucion(ido, ahora, anterior)
		self.assertEqual(atribucion["categoria"], "app")
		self.assertIn("vinculada", atribucion["texto"])

	def test_si_el_acto_NO_ocurrio_no_se_lo_inventa(self):
		"""LA GUARDA DE LA SEGUNDA CATEGORÍA. Se comprueba contra la base antes de
		afirmar: sin la clasificación puesta, el hallazgo desapareció por otra cosa."""
		anterior = self._corrida()
		ido = self._hallazgo(anterior, tipo="classification_missing", sujeto="")
		ahora = self._corrida()

		self.assertEqual(
			self.Delta.atribucion(ido, ahora, anterior)["categoria"], "fuera")

	# --- 3 · fuera de la app ---

	def test_sin_plan_y_sin_acto_se_afirma_FUERA_DE_LA_APP(self):
		"""Y se puede afirmar: el embudo es el ÚNICO camino por el que este módulo
		escribe en GitHub. Si ningún plan lo tocó y no fue un acto de acá, alguien lo
		cambió por otro lado. No es suposición: es lo que queda."""
		anterior = self._corrida()
		ido = self._hallazgo(anterior)
		ahora = self._corrida()

		atribucion = self.Delta.atribucion(ido, ahora, anterior)

		self.assertEqual(atribucion["categoria"], "fuera")
		self.assertIn("fuera de la app", atribucion["texto"])

	# --- y llega a la pantalla ---

	def test_la_pantalla_recibe_la_atribucion_de_cada_resuelto(self):
		anterior = self._corrida(cuando=datetime(2026, 9, 1, 10, 0))
		ido = self._hallazgo(anterior)
		self._plan_aplicado(ido, datetime(2026, 9, 3, 12, 0))
		ahora = self._corrida(cuando=datetime(2026, 9, 8, 10, 0))

		datos = self.Delta.para_pantalla(ahora.id)

		self.assertEqual(len(datos["resueltos"]), 1)
		self.assertEqual(datos["resueltos"][0]["atribucion"], "plan")
		self.assertIn("verificado", datos["resueltos"][0]["nota"])

	def test_dos_plantillas_sin_checks_son_DOS_hallazgos_y_no_uno(self):
		"""La clave los distingue sólo si el hallazgo lleva sujeto.

		Sin sujeto, `(checks_not_evaluable, sin repo, sin sujeto)` es la misma clave para
		las dos, y el delta las colapsaba: definir los checks de una se leía como si se
		hubieran definido los de las dos.

		LOS HALLAZGOS LOS PRODUCE EL MOTOR, no este test. La primera versión los creaba a
		mano —con el sujeto puesto por el test— y por eso pasaba en verde con el motor
		mutado: comprobaba lo que el código debería hacer en vez de lo que hace. Es el
		antipatrón que el propio CLAUDE.md documenta, cometido de nuevo.
		"""
		clasificaciones = [c[0] for c in self.env[
			"repo.policy.template"]._fields["classification_default"].selection][:2]
		self.assertEqual(len(clasificaciones), 2, "hacen falta dos clasificaciones")
		nombres = []
		for clasificacion in clasificaciones:
			# Una plantilla por clasificación, y la de fábrica desactivada: sólo puede
			# haber una activa por clasificación.
			self.env["repo.policy.template"].with_context(active_test=False).search([
				("classification_default", "=", clasificacion)]).write({"active": False})
			self.env.flush_all()
			nombre = "Sin checks %s %s" % (clasificacion, uuid.uuid4().hex[:4])
			self.env["repo.policy.template"].create({
				"name": nombre, "code": "sc-%s" % uuid.uuid4().hex[:6],
				"classification_default": clasificacion,
				"status_checks_defined": False})
			nombres.append(nombre)
			self.env["repo.repository"].create({
				"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
				"name": "r-%s" % clasificacion, "full_name": "cuenta/r-%s" % clasificacion,
				"classification": clasificacion,
				"classification_source": "manual"})

		corrida = self._corrida()
		self.env["repo.audit.engine"].evaluate(corrida)

		# Se los busca por el RESUMEN y no por el sujeto: si se filtrara por sujeto, la
		# mutación que se lo quita haría desaparecer los hallazgos del filtro y el test
		# fallaría por no encontrarlos — un rojo por el motivo equivocado. Así el rojo
		# cae donde tiene que caer: en la clave colapsada.
		suyos = corrida.finding_ids.filtered(
			lambda h: h.finding_type == "checks_not_evaluable"
			and any(n in (h.summary or "") for n in nombres))
		self.assertEqual(len(suyos), 2, "el motor no emitió uno por plantilla")
		self.assertEqual(
			len({self.Delta.clave(h) for h in suyos}), 2,
			"las dos plantillas comparten la clave: el delta las va a colapsar")
