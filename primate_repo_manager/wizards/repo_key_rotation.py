# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Rotación del secreto de cifrado.

Sin esto, rotar `repo_manager_key` en odoo.conf rompe la conexión EN SILENCIO: la private
key guardada quedó cifrada con el secreto viejo y ya no se puede descifrar, pero nada
avisa hasta que alguien intenta auditar semanas después.

El orden es a propósito: primero se cambia el odoo.conf y se reinicia, después se corre
este asistente pegando el secreto ANTERIOR. Así en ningún momento hay un estado donde la
base esté cifrada con una clave que el archivo de configuración ya no tiene.
"""
import base64
import hashlib
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RepoKeyRotation(models.TransientModel):
	_name = "repo.key.rotation"
	_description = "Rotar el secreto de cifrado de las credenciales"

	previous_key = fields.Text(
		string="Secreto anterior", required=True,
		help="El valor que tenía `repo_manager_key` en odoo.conf ANTES de cambiarlo.")
	backend_ids = fields.Many2many(
		"repo.backend", string="Conexiones a recifrar",
		default=lambda self: self.env["repo.backend"].search(
			[("private_key_encrypted", "!=", False)]))
	preview = fields.Text(string="Resultado", readonly=True)

	def _fernet_con(self, secreto):
		"""Fernet derivado de un secreto arbitrario. Misma derivación que repo.backend."""
		from cryptography.fernet import Fernet

		if len((secreto or "").strip()) < 32:
			raise UserError(_("El secreto anterior es demasiado corto (mínimo 32 caracteres)."))
		clave = base64.urlsafe_b64encode(
			hashlib.sha256(("repo_manager:%s" % secreto).encode()).digest())
		return Fernet(clave)

	def action_verify(self):
		"""Prueba a descifrar SIN escribir nada. Primero mirar, después tocar."""
		self.ensure_one()
		lineas = []
		for backend in self.backend_ids:
			ok, detalle = self._probar(backend)
			lineas.append("%s %s — %s" % ("✓" if ok else "✗", backend.name, detalle))
		self.preview = "\n".join(lineas) or _("No hay conexiones con clave guardada.")
		return {
			"type": "ir.actions.act_window", "res_model": self._name,
			"res_id": self.id, "view_mode": "form", "target": "new",
		}

	def _probar(self, backend):
		from cryptography.fernet import InvalidToken

		try:
			self._fernet_con(self.previous_key).decrypt(
				backend.private_key_encrypted.encode())
			return True, _("se descifra con el secreto anterior")
		except InvalidToken:
			pass
		# Puede que ya esté recifrada: rotar dos veces no debe romper nada.
		try:
			backend._descifrar()
			return True, _("ya estaba cifrada con el secreto actual, no hay que tocarla")
		except UserError:
			return False, _("no se descifra ni con el anterior ni con el actual")

	def action_rotate(self):
		"""Descifra con el secreto viejo y recifra con el que hay hoy en odoo.conf."""
		self.ensure_one()
		from cryptography.fernet import InvalidToken

		anterior = self._fernet_con(self.previous_key)
		rotadas, salteadas, fallidas = [], [], []
		for backend in self.backend_ids:
			try:
				plano = anterior.decrypt(backend.private_key_encrypted.encode()).decode()
			except InvalidToken:
				try:
					backend._descifrar()
					salteadas.append(backend.name)
				except UserError:
					fallidas.append(backend.name)
				continue
			# _cifrar usa el secreto actual de odoo.conf; si falta, levanta y no escribe.
			backend.private_key_encrypted = backend._cifrar(plano)
			backend.message_post(body=_(
				"Se rotó el secreto de cifrado: la private key se recifró con la clave "
				"actual de odoo.conf. El valor de la clave no cambió."))
			rotadas.append(backend.name)

		if fallidas:
			# No se deja a medias en silencio: lo que no se pudo, se dice.
			raise UserError(_(
				"Recifré %(ok)s conexión(es), pero NO pude con: %(mal)s.\n\n"
				"Esas credenciales no se descifran ni con el secreto anterior que pegaste "
				"ni con el actual. Hay que volver a cargar el .pem de la GitHub App en "
				"cada una."
			) % {"ok": len(rotadas), "mal": ", ".join(fallidas)})

		_logger.info("Repo Manager: secreto rotado en %s conexión(es)", len(rotadas))
		self.preview = _(
			"Recifradas: %(ok)s. Ya estaban al día: %(skip)s."
		) % {"ok": ", ".join(rotadas) or "—", "skip": ", ".join(salteadas) or "—"}
		return {
			"type": "ir.actions.act_window", "res_model": self._name,
			"res_id": self.id, "view_mode": "form", "target": "new",
		}
