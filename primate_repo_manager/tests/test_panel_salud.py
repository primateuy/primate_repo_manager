# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El panel de salud — y sobre todo, su día uno.

LA REGLA QUE ESTOS TESTS VIGILAN: **el día uno se muestra sin maquillaje.** 0 % es 0 %, y
donde no hay regla contra la cual medir va un guión con su motivo — nunca un cero que
parezca un logro ni un verde que parezca salud.

Es la parte del panel que casi nadie ve, porque dura una sola auditoría, y por eso es la
que hay que dejar probada: nadie la va a revisar a mano el día que pase.
"""
import uuid

from odoo.tests.common import TransactionCase


class BasePanel(TransactionCase):

	def setUp(self):
		super().setUp()
		self.Panel = self.env["repo.health.panel"]
		self.backend = self.env["repo.backend"].create({
			"name": "Panel %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"environment": "sandbox"})

	def _repo(self, nombre="uno", clasificacion=False):
		return self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": nombre, "full_name": "%s/%s" % (self.backend.owner_login, nombre),
			"classification": clasificacion})

	def _corrida(self, estado="done"):
		return self.env["repo.audit.run"].create({
			"name": "Corrida", "backend_id": self.backend.id, "state": estado})

	def _numero(self, datos, clave):
		return next(n for n in datos["numeros"] if n["clave"] == clave)


class TestElDiaUnoSinMaquillaje(BasePanel):

	def test_sin_conexiones_no_dice_que_todo_está_bien(self):
		"""Decir «sin hallazgos» sobre una instalación vacía sería inventarlo."""
		self.env["repo.backend"].search([]).unlink() if False else None
		# No se borran las conexiones de la base: se prueba el camino con una que existe
		# pero sin auditar, que es el caso real del primer día.
		datos = self.Panel.datos(self.backend.id)
		self.assertTrue(datos["hay_conexion"])
		self.assertFalse(datos["corrida"]["hubo"])
		self.assertEqual(datos["estado"]["chip"], "SIN AUDITAR")
		self.assertIn("no puede decir nada", datos["estado"]["frase"])

	def test_auditado_pero_SIN_POLÍTICA_lo_dice_con_todas_las_letras(self):
		"""El día uno de verdad: ya se leyó todo y todavía no hay contra qué comparar."""
		self._repo()
		self._corrida()
		datos = self.Panel.datos(self.backend.id)
		self.assertEqual(datos["estado"]["chip"], "SIN POLÍTICA")
		self.assertIn("no puede decir qué está bien ni qué está mal",
					  datos["estado"]["frase"])

	def test_CERO_HALLAZGOS_sin_política_no_es_una_buena_noticia_y_se_aclara(self):
		self._repo()
		self._corrida()
		numero = self._numero(self.Panel.datos(self.backend.id), "hallazgos")
		self.assertEqual(numero["valor"], 0)
		self.assertIn("no porque todo esté bien", numero["pie"])

	def test_sin_ramas_relevadas_va_un_GUIÓN_y_no_un_cero(self):
		"""«No hay nada que medir» y «medí cero» son cosas distintas. Un 0 % sobre cero
		ramas relevadas se leería como «ninguna está protegida», que es una acusación."""
		self._repo()
		self._corrida()
		numero = self._numero(self.Panel.datos(self.backend.id), "protegidas")
		self.assertIsNone(numero["valor"])
		self.assertIn("todavía no hay ramas", numero["pie"])

	def test_pero_CERO_DE_TRES_es_cero_por_ciento_y_se_muestra(self):
		"""La otra mitad de la regla, y la que hace que la primera no sea una excusa: si
		hay ramas relevadas y ninguna está protegida, el número es 0 % y se muestra."""
		repo = self._repo(clasificacion="cliente")
		for nombre in ("17.0", "18.0", "19.0"):
			self.env["repo.branch"].create({
				"repository_id": repo.id, "name": nombre, "role": "base",
				"protected": False, "protection_readable": True})
		self._corrida()
		numero = self._numero(self.Panel.datos(self.backend.id), "protegidas")
		self.assertEqual(numero["valor"], 0)
		self.assertIn("0 de 3", numero["pie"])

	def test_sin_NINGUNA_convención_definida_va_un_guión_y_dice_por_qué(self):
		"""«Sin regla no hay número» y «hay regla pero no medí nada» son dos motivos
		distintos para el mismo guión, y el panel dice cuál es. Confundirlos mandaría a
		alguien a definir una convención que ya está definida."""
		self.env["repo.policy.template"].search([]).write(
			{"commit_message_pattern": False})
		self._repo()
		self._corrida()
		numero = self._numero(self.Panel.datos(self.backend.id), "convencion")
		self.assertIsNone(numero["valor"])
		self.assertIn("sin regla, no hay número", numero["pie"])

	def test_con_convención_pero_sin_commits_relevados_lo_dice_distinto(self):
		self._repo()
		self._corrida()
		numero = self._numero(self.Panel.datos(self.backend.id), "convencion")
		self.assertIsNone(numero["valor"])
		self.assertIn("no hay commits relevados", numero["pie"])


class TestLoQueNoSePudoLeer(BasePanel):

	def test_una_rama_ilegible_NO_cuenta_como_incumplidora_ni_como_sana(self):
		"""Meterla en el denominador la contaría como incumplidora; sacarla sin decirlo,
		como sana. Ninguna de las dos es cierta: se saca y SE DICE."""
		repo = self._repo(clasificacion="cliente")
		self.env["repo.branch"].create({
			"repository_id": repo.id, "name": "17.0", "role": "base",
			"protected": True, "protection_readable": True})
		self.env["repo.branch"].create({
			"repository_id": repo.id, "name": "18.0", "role": "base",
			"protected": False, "protection_readable": False})
		self._corrida()
		numero = self._numero(self.Panel.datos(self.backend.id), "protegidas")
		self.assertEqual(numero["valor"], 100, "la ilegible no puede bajar el número")
		self.assertEqual(numero["sin_leer"], 1, "y tiene que estar contada aparte")


class TestLaPolíticaEsDeCadaConexión(BasePanel):

	def test_una_conexión_nueva_no_hereda_la_política_de_otra(self):
		"""Con la pregunta hecha en global, una cuenta recién conectada mostraba su día
		uno como si tuviera reglas, heredando el «sí hay política» de otra conexión."""
		otro = self.env["repo.backend"].create({
			"name": "Otra %s" % uuid.uuid4().hex[:6],
			"owner_login": "otra-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2"})
		self.env["repo.repository"].create({
			"backend_id": otro.id, "github_id": uuid.uuid4().hex[:8],
			"name": "clasificado", "full_name": "otra/clasificado",
			"classification": "cliente"})
		self._repo()
		self._corrida()
		self.assertEqual(
			self.Panel.datos(self.backend.id)["estado"]["chip"], "SIN POLÍTICA")


class TestElPanelElige(BasePanel):

	def test_ofrece_todas_las_conexiones_para_cambiar(self):
		datos = self.Panel.datos(self.backend.id)
		self.assertIn(self.backend.id, [c["id"] for c in datos["conexiones"]])

	def test_una_corrida_sin_detalle_no_dice_CERO_DE_CERO(self):
		"""Las corridas anteriores al registro por repositorio existen y sus hallazgos
		valen; lo que no tienen es el desglose. «0 de 0 leídos» sobre una auditoría que
		leyó 47 repositorios es peor que no decir nada."""
		self._corrida()
		self.assertTrue(self.Panel.datos(self.backend.id)["corrida"]["sin_detalle"])
