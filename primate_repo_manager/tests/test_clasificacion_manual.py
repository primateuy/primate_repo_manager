# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""La promesa que el módulo le hace a quien clasifica 43 repositorios a mano.

La promesa está escrita en el `help` del campo: «una auditoría NUNCA pisa una
clasificación manual; corregir un repo a mano y ver cómo se revierte solo sería la forma
más rápida de perderle la confianza a la herramienta». El mecanismo existía
—`classification_source`— pero no había nada que lo pusiera en «manual» cuando alguien
editaba el campo desde un formulario: se guardaba, quedaba en «heurística», y la corrida
siguiente lo pisaba en silencio.

Estos tests son esa promesa. El que importa es
`test_una_clasificacion_puesta_a_mano_sobrevive_a_la_auditoria`: es el defecto caro, el
que se habría descubierto con los 43 repositorios ya perdidos.
"""
import uuid

from odoo.tests.common import TransactionCase

from .test_backend import _clave_rsa_de_prueba


class TestClasificacionManual(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Clasif %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected", "environment": "sandbox",
		})
		self.backend.private_key = self.clave

	def _repo(self, nombre="sbx-lo-que-sea", **extra):
		valores = {
			"backend_id": self.backend.id, "name": nombre,
			"full_name": "%s/%s" % (self.backend.owner_login, nombre),
			"github_id": uuid.uuid4().hex[:8],
		}
		valores.update(extra)
		return self.env["repo.repository"].create(valores)

	# --- EL test: la promesa ------------------------------------------------

	def test_una_clasificacion_puesta_a_mano_sobrevive_a_la_auditoria(self):
		"""El defecto caro, en un test.

		El repositorio se llama de forma que la heurística lo mandaría a `localizacion`.
		Una persona decide que es de cliente. La auditoría vuelve a pasar y NO puede
		cambiarlo.

		MUTACIÓN OBLIGATORIA: quitando `classification_source="manual"` del `write` de
		`repo.repository`, este test se pone rojo — la auditoría pisa la decisión. Es la
		comprobación de que el test prueba la promesa y no la implementación.
		"""
		repo = self._repo("sbx-localizacion-uy")
		datos = {"name": "sbx-localizacion-uy", "fork": False, "private": False}

		# Primero la heurística, para tener de dónde caerse.
		repo._apply_classification(datos)
		self.assertEqual(repo.classification, "localizacion")
		self.assertEqual(repo.classification_source, "auto")

		# Ahora decide una persona, editando el campo y nada más.
		repo.classification = "cliente"
		self.assertEqual(repo.classification_source, "manual",
						 "editar el campo ES el acto manual")

		# Y la auditoría vuelve a pasar.
		repo._apply_classification(datos)
		self.assertEqual(repo.classification, "cliente",
						 "la auditoría pisó una clasificación decidida por una persona")
		self.assertEqual(repo.classification_source, "manual")

	# --- el otro lado del mismo filo ---------------------------------------

	def test_la_heuristica_no_se_marca_a_si_misma_como_manual(self):
		"""Si la heurística se marcara manual, se congelaría en la primera corrida.

		Es el error simétrico y es igual de malo: la clasificación automática dejaría de
		corregirse sola cuando cambian las reglas o el repositorio se renombra.

		MUTACIÓN: quitando la bandera `SIN_MANO` de `_apply_classification`, rojo.
		"""
		repo = self._repo("sbx-localizacion-uy")
		repo._apply_classification(
			{"name": "sbx-localizacion-uy", "fork": False, "private": False})
		self.assertEqual(repo.classification, "localizacion")
		self.assertEqual(repo.classification_source, "auto")

		# Y sigue corrigiéndose sola: el mismo repo, ahora detectado como fork.
		repo._apply_classification(
			{"name": "sbx-localizacion-uy", "fork": True, "private": False})
		self.assertEqual(repo.classification, "fork_upstream")
		self.assertEqual(repo.classification_source, "auto")

	def test_el_lote_pasa_por_la_misma_puerta_que_la_edicion_de_a_uno(self):
		"""43 repositorios de a uno no es un flujo. Pero el atajo no puede ser un agujero."""
		repos = self.env["repo.repository"].browse()
		for n in range(3):
			repos |= self._repo("sbx-sin-regla-%s" % n)
		self.assertTrue(all(r.classification_source == "auto" for r in repos))

		repos.write({"classification": "cliente"})

		self.assertTrue(all(r.classification == "cliente" for r in repos))
		self.assertTrue(all(r.classification_source == "manual" for r in repos),
						"el lote tiene que marcar igual que la edición de a uno")

	def test_escribir_otra_cosa_no_toca_el_origen(self):
		"""Sólo la clasificación decide sobre el origen de la clasificación."""
		repo = self._repo()
		repo.classification = "interno"
		repo.classification_source = "auto"          # se fuerza para la prueba
		repo.write({"description": "otra cosa"})
		self.assertEqual(repo.classification_source, "auto")

	def test_los_dos_campos_de_la_decision_estan_seguidos(self):
		"""Una decisión con consecuencias tiene que dejar rastro sin que nadie lo pida.

		SE PRUEBA LA DECLARACIÓN, NO EL MENSAJE, y conviene ser claro sobre por qué. Odoo
		difiere el seguimiento y, para un registro creado en la MISMA transacción que la
		edición, no llega a producir la entrada: un test que mirara `message_ids` acá daría
		rojo por mecánica del framework y no por el módulo. Lo que sí es del módulo —y lo
		único que hace falta para que la entrada exista— es que los dos campos estén
		declarados con `tracking`.

		El comportamiento en vivo se comprobó sobre un registro real de `prm-sandbox`:
		cambiar la clasificación llevó el chatter de 1 a 2 mensajes, con seguimiento de
		`classification` y de `classification_source`.
		"""
		campos = self.env["repo.repository"]._fields
		self.assertTrue(campos["classification"].tracking)
		self.assertTrue(campos["classification_source"].tracking,
						"sin esto, el chatter diría qué se eligió pero no que lo eligió "
						"una persona, que es la mitad que importa")


class TestNavegacionSinCallejones(TransactionCase):
	"""El camino corrida → hallazgos → repositorio → sus hallazgos, ida y vuelta."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Nav %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected", "environment": "sandbox",
		})
		self.backend.private_key = self.clave
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "name": "sbx-uno",
			"full_name": "%s/sbx-uno" % self.backend.owner_login,
			"github_id": uuid.uuid4().hex[:8],
		})
		self.vieja = self.env["repo.audit.run"].create({
			"name": "Vieja", "backend_id": self.backend.id, "state": "done"})
		self.nueva = self.env["repo.audit.run"].create({
			"name": "Nueva", "backend_id": self.backend.id, "state": "done"})
		Finding = self.env["repo.audit.finding"]
		for corrida, cuantos in ((self.vieja, 3), (self.nueva, 2)):
			for n in range(cuantos):
				Finding.create({
					"run_id": corrida.id, "repository_id": self.repo.id,
					"finding_type": "branch_unprotected", "severity": "high",
					"summary": "hallazgo %s de %s" % (n, corrida.name),
				})

	def test_el_conteo_del_repositorio_es_el_de_la_ultima_corrida(self):
		"""Un número que suma seis auditorías del mismo problema no dice cuántos
		problemas hay: dice cuántas veces se miró."""
		self.assertEqual(self.repo.last_run_id, self.nueva)
		self.assertEqual(self.repo.finding_count, 2)
		self.assertEqual(len(self.repo.finding_ids), 5,
						 "el historial no se borra ni se esconde, sólo no se cuenta")

	def test_desde_el_repositorio_se_llega_a_sus_hallazgos(self):
		accion = self.repo.action_open_findings()
		self.assertEqual(accion["res_model"], "repo.audit.finding")
		self.assertIn(("repository_id", "=", self.repo.id), accion["domain"])
		self.assertEqual(accion["context"]["search_default_run_id"], self.nueva.id,
						 "la última corrida viene filtrada, y se saca con un click")

	def test_el_filtro_de_la_ultima_corrida_es_quitable_no_cableado(self):
		"""Un dominio fijo escondería el historial sin decirlo. El filtro se ve y se saca."""
		accion = self.repo.action_open_findings()
		aplanado = str(accion["domain"])
		self.assertNotIn("run_id", aplanado,
						 "la corrida va como filtro por defecto, NO como dominio")

	def test_desde_la_corrida_se_llega_a_sus_hallazgos(self):
		accion = self.nueva.action_open_findings()
		self.assertEqual(accion["res_model"], "repo.audit.finding")
		self.assertIn(("run_id", "=", self.nueva.id), accion["domain"])


class TestOrdenDeSeveridades(TransactionCase):
	"""Los grupos de severidad tienen que salir en orden de gravedad.

	Lo destapó una captura para la guía: la lista agrupada mostraba
	«Crítico, Alto, Informativo, Medio». Odoo ordena los grupos de un campo de selección
	por el VALOR guardado —alfabéticamente— y no por el orden en que la selección está
	declarada; con los valores naturales, `info` cae antes que `medium`. En una lista cuyo
	único propósito es triaje, eso no es un detalle estético.
	"""

	def test_los_rangos_ordenan_igual_que_la_gravedad(self):
		from ..models.repo_audit_finding import (
			RANK_BY_SEVERITY, SEVERITIES, SEVERITY_ORDER)

		por_gravedad = sorted(SEVERITY_ORDER, key=lambda s: SEVERITY_ORDER[s])
		por_alfabeto = sorted(por_gravedad, key=lambda s: RANK_BY_SEVERITY[s])
		self.assertEqual(por_gravedad, por_alfabeto,
						 "ordenar los rangos como texto tiene que dar el mismo orden que "
						 "la gravedad: es lo único que hace que los grupos salgan bien")
		self.assertEqual(set(RANK_BY_SEVERITY), {v for v, _e in SEVERITIES},
						 "toda severidad necesita su rango, o su grupo desaparece")

	def test_cada_hallazgo_lleva_su_rango(self):
		from ..models.repo_audit_finding import RANK_BY_SEVERITY

		backend = self.env["repo.backend"].create({
			"name": "Sev %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2"})
		corrida = self.env["repo.audit.run"].create({
			"name": "x", "backend_id": backend.id})
		for severidad in RANK_BY_SEVERITY:
			hallazgo = self.env["repo.audit.finding"].create({
				"run_id": corrida.id, "finding_type": "classification_missing",
				"severity": severidad, "summary": "x"})
			self.assertEqual(hallazgo.severity_rank, RANK_BY_SEVERITY[severidad])
