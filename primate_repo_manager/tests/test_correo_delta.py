# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""E2.3 · el correo del lunes y el aviso en Discuss.

LO QUE MÁS SE VIGILA ACÁ ES EL SILENCIO. Un correo que no llega no se nota: se lee como
«no hubo novedades», y la semana que la auditoría falla es justamente la semana en la que
nadie está mirando. Por eso hay más tests sobre cuándo SE MANDA que sobre qué dice.
"""
import re
import uuid

from odoo import fields
from odoo.tests.common import TransactionCase


class BaseCorreo(TransactionCase):

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Correo %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2",
			"state": "connected"})
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "uno", "full_name": "cuenta/uno"})
		self.Correo = self.env["repo.delta.mail"]

	def _corrida(self, state="done", origin="scheduled", lineas="done"):
		corrida = self.env["repo.audit.run"].create({
			"name": "C %s" % uuid.uuid4().hex[:4], "backend_id": self.backend.id,
			"state": state, "origin": origin,
			"finished_at": fields.Datetime.now()})
		self.env["repo.audit.run.line"].create({
			"run_id": corrida.id, "repository_id": self.repo.id, "state": lineas,
			"error": "GitHub 403: Resource not accessible" if lineas == "error" else False})
		return corrida

	def _hallazgo(self, corrida, severidad="critical", sujeto="19.0"):
		return self.env["repo.audit.finding"].create({
			"run_id": corrida.id, "repository_id": self.repo.id,
			"finding_type": "branch_unprotected", "severity": severidad,
			"subject": sujeto, "summary": "la rama %s quedó sin protección" % sujeto})


class TestElCuerpoDelCorreo(BaseCorreo):

	def test_los_tokens_del_correo_son_LOS_MISMOS_del_sistema(self):
		"""EL DUPLICADO ATADO. Los clientes de correo no cargan hojas de estilo, así que
		el color va escrito en cada elemento y los tokens quedan en dos lados.

		Duplicar el sistema de diseño es lo que este proyecto no hace, así que el
		duplicado se ata: este test lee `tokens.scss` y exige que los valores del correo
		sean los mismos. El día que el diseño cambie un rojo, esto se pone en rojo — que
		es exactamente lo que tiene que pasar.
		"""
		from ..models.repo_delta_mail import T

		ruta = "%s/static/src/scss/tokens.scss" % __file__.rsplit("/tests/", 1)[0]
		with open(ruta, encoding="utf-8") as archivo:
			scss = archivo.read()
		equivalencias = {
			"ink": "--rm-ink", "ink_3": "--rm-ink-3", "border": "--rm-border",
			"bg": "--rm-bg", "surface": "--rm-surface",
			"critical": "--rm-sev-critical", "high": "--rm-sev-high",
			"medium": "--rm-sev-medium", "info": "--rm-sev-info",
			"done": "--rm-done", "error": "--rm-error", "accent": "--rm-accent",
		}
		for clave, token in equivalencias.items():
			encontrado = re.search(
				r"%s:\s*(#[0-9A-Fa-f]{6})\s*;" % re.escape(token), scss)
			self.assertTrue(encontrado, "el token %s no está en tokens.scss" % token)
			self.assertEqual(
				T[clave].upper(), encontrado.group(1).upper(),
				"el correo usa otro valor que el sistema para %s" % token)

	def test_el_correo_NO_lleva_hojas_de_estilo_externas(self):
		"""Si las llevara, el lunes se vería como texto plano en la mitad de los
		clientes — y sería invisible desde acá."""
		corrida = self._corrida()
		self._hallazgo(corrida)
		cuerpo = self.Correo.cuerpo(corrida)
		self.assertNotIn("<link", cuerpo)
		self.assertNotIn("class=", cuerpo)
		self.assertIn("style=", cuerpo)

	def test_lo_nuevo_va_ordenado_por_gravedad(self):
		"""Se lee en el teléfono: lo crítico no puede estar tercero."""
		anterior = self._corrida()
		corrida = self._corrida()
		self._hallazgo(corrida, severidad="medium", sujeto="17.0")
		self._hallazgo(corrida, severidad="critical", sujeto="19.0")
		cuerpo = self.Correo.cuerpo(corrida)
		self.assertLess(cuerpo.index("19.0"), cuerpo.index("17.0"))

	def test_la_frase_de_los_no_leidos_dice_que_el_correo_no_habla_de_ellos(self):
		"""Sin ella, los tres números de arriba se leen como si hablaran de toda la
		cuenta. Hablan de lo que se pudo mirar."""
		anterior = self._corrida()
		self._hallazgo(anterior)
		corrida = self._corrida(state="partial", lineas="error")
		cuerpo = self.Correo.cuerpo(corrida)
		self.assertIn("Sin leer", cuerpo)
		self.assertIn("no dice nada sobre ellos", cuerpo)
		self.assertIn("403", cuerpo)

	def test_un_repo_ilegible_SIN_hallazgos_previos_igual_se_nombra(self):
		"""LO QUE EL ENSAYO E2.4 ENCONTRÓ.

		La caja punteada salía del bloque «sin confirmar» del delta, que habla de
		HALLAZGOS que no se pueden dar por resueltos y por eso sólo lista repositorios
		que ya tenían alguno. Un repositorio nuevo que no se pudo leer quedaba fuera de
		los tres números de arriba y el correo no lo decía.

		Esta frase habla de los NÚMEROS: cualquiera que no se pudo mirar va nombrado,
		haya tenido hallazgos antes o no.
		"""
		self._corrida()  # una anterior, para que haya con qué comparar
		corrida = self._corrida(state="partial", lineas="error")
		# El repositorio no tuvo NUNCA un hallazgo: es nuevo y falló en su primera
		# lectura, que es exactamente el caso del ensayo.
		self.assertFalse(corrida.finding_ids)
		cuerpo = self.Correo.cuerpo(corrida)
		self.assertIn("Sin leer", cuerpo)
		self.assertIn(self.repo.full_name, cuerpo)

	def test_el_correo_de_una_auditoria_FALLIDA_dice_qué_pasó(self):
		corrida = self._corrida(state="error")
		corrida.error_detail = "El token venció (401)"
		cuerpo = self.Correo.cuerpo(corrida)
		self.assertIn("no pudo terminar", cuerpo)
		self.assertIn("401", cuerpo)
		self.assertIn("semana pasada", cuerpo)

	def test_el_asunto_de_la_fallida_lo_dice_en_el_asunto(self):
		"""Quien lo lee en el teléfono ve el asunto antes que nada."""
		self.assertIn("no pudo terminar",
					  self.Correo.asunto(self._corrida(state="error")))

	def test_el_asunto_cuenta_los_criticos(self):
		corrida = self._corrida()
		self._hallazgo(corrida, severidad="critical")
		self.assertIn("crítico", self.Correo.asunto(corrida))


class TestCuandoSeManda(BaseCorreo):

	def setUp(self):
		super().setUp()
		self.destinatario = self.env["res.partner"].create(
			{"name": "Quien mira", "email": "quien@example.com"})
		self.env["ir.config_parameter"].sudo().set_param(
			"repo_manager.delta_recipient_ids", str(self.destinatario.id))

	def _mensajes(self, corrida):
		return corrida.message_ids.filtered(
			lambda m: self.destinatario in m.partner_ids)

	def test_una_corrida_PROGRAMADA_manda_el_resumen(self):
		corrida = self._corrida(origin="scheduled")
		self.assertTrue(corrida._notificar_delta())
		self.assertTrue(self._mensajes(corrida))

	def test_una_corrida_A_MANO_no_manda_nada(self):
		"""Ya hay alguien mirando la pantalla. Un correo de lo que está viendo es la
		clase de ruido que hace que el correo del lunes se ignore."""
		corrida = self._corrida(origin="manual")
		self.assertFalse(corrida._notificar_delta())
		self.assertFalse(self._mensajes(corrida))

	def test_una_corrida_FALLIDA_manda_el_correo_IGUAL(self):
		"""LA GUARDA CONTRA EL SILENCIO. No mandar nada dejaría creer que no hay
		novedades, y la semana que la auditoría falla es la semana en la que nadie está
		mirando."""
		corrida = self._corrida(state="error", origin="scheduled")
		self.assertTrue(corrida._notificar_delta())
		mensajes = self._mensajes(corrida)
		self.assertTrue(mensajes)
		self.assertIn("no pudo terminar", "".join(mensajes.mapped("subject")))

	def test_sin_destinatarios_no_revienta_la_auditoria(self):
		self.env["ir.config_parameter"].sudo().set_param(
			"repo_manager.delta_recipient_ids", "")
		# Y el de fábrica es el administrador, así que sigue habiendo a quién.
		self.assertTrue(self.env["repo.settings"]._destinatarios())

	def test_de_fabrica_le_llega_a_quien_administra_la_instancia(self):
		self.env["ir.config_parameter"].sudo().set_param(
			"repo_manager.delta_recipient_ids", "")
		admin = self.env.ref("base.user_admin")
		self.assertEqual(self.env["repo.settings"]._destinatarios(), admin.partner_id)

	def test_un_destinatario_borrado_no_deja_el_correo_sin_destino(self):
		"""El id queda en la configuración y el contacto ya no está: si se devolviera
		tal cual, el correo saldría a la nada y nadie se enteraría.

		NO ALCANZA CON `assertTrue`: `browse` de un id inexistente devuelve un recordset
		VERDADERO, así que la primera versión de este test pasaba con la guarda sacada.
		Lo que hay que comprobar es que lo devuelto EXISTA — y que, no existiendo, se
		caiga al destinatario de fábrica.
		"""
		self.env["ir.config_parameter"].sudo().set_param(
			"repo_manager.delta_recipient_ids", "999999999")
		destinatarios = self.env["repo.settings"]._destinatarios()
		self.assertTrue(destinatarios)
		self.assertEqual(
			destinatarios, destinatarios.exists(),
			"se devolvió un contacto que ya no existe: el correo saldría a la nada")
		self.assertEqual(destinatarios, self.env.ref("base.user_admin").partner_id)

	def test_el_resumen_que_no_se_puede_armar_NO_tumba_la_auditoria(self):
		"""La auditoría es lo que importa; el correo es su consecuencia. Un error
		armando el resumen no puede perder la corrida entera."""
		corrida = self._corrida(origin="scheduled")
		corrida.finished_at = False
		corrida.started_at = False
		# `_cuando` no tiene con qué formatear: el resumen falla y se registra.
		self.assertIn(corrida._notificar_delta(), (True, False))
