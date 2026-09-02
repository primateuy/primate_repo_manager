# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Conexión a GitHub como App instalada.

Sobre `owner_type`: la spec habla de "la organización", pero los 94 repos de Primate
cuelgan hoy de la **cuenta de usuario** `primateuy`; la org `PrimateUy-SAS` tiene un repo
y ningún team. Los endpoints difieren (`/users/{login}/repos` vs `/orgs/{login}/repos`) y
los teams sólo existen en organizaciones. Modelar el dueño como usuario u organización
desde el principio cuesta un campo y evita reescribir el mapeo el día que migren.
"""
import base64
import hashlib
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .github_client import GithubAppAuth, GithubError, GithubReadClient

_logger = logging.getLogger(__name__)


class RepoBackend(models.Model):
	_name = "repo.backend"
	_description = "Conexión a un proveedor de repositorios (GitHub App)"
	_inherit = ["mail.thread"]
	_order = "name"

	name = fields.Char(string="Nombre", required=True, tracking=True)
	provider = fields.Selection(
		[("github", "GitHub")], string="Proveedor", default="github", required=True)
	owner_login = fields.Char(
		string="Cuenta", required=True, tracking=True,
		help="Login de la cuenta dueña de los repos. Ej: 'primateuy'.")
	owner_type = fields.Selection(
		[("user", "Cuenta de usuario"), ("organization", "Organización")],
		string="Tipo de cuenta", default="user", required=True, tracking=True,
		help="Cambia los endpoints que se recorren y si existen teams. Una cuenta de "
			 "usuario no tiene teams ni miembros de organización.")

	app_id = fields.Char(string="App ID", tracking=True)
	installation_id = fields.Char(string="Installation ID", tracking=True)
	# Write-only: se escribe pero nunca se devuelve. Ver _compute_private_key.
	private_key = fields.Text(
		string="Private key (PEM)", compute="_compute_private_key",
		inverse="_inverse_private_key", store=False,
		help="Se guarda cifrada. Una vez guardada no se vuelve a mostrar.")
	private_key_encrypted = fields.Text(string="Private key cifrada", copy=False)
	private_key_set = fields.Boolean(
		string="Clave cargada", compute="_compute_private_key_set", store=True)

	state = fields.Selection(
		[("draft", "Sin probar"), ("connected", "Conectado"), ("error", "Error")],
		string="Estado", default="draft", required=True, tracking=True, copy=False)
	last_sync = fields.Datetime(string="Última auditoría", readonly=True, copy=False)
	last_error = fields.Text(string="Último error", readonly=True, copy=False)
	rate_remaining = fields.Integer(string="Cuota API restante", readonly=True, copy=False)

	environment = fields.Selection(
		[("sandbox", "Sandbox"), ("production", "Producción")],
		string="Entorno", default="production", required=True, tracking=True,
		help="Sandbox es la cuenta de prueba con repos dummy donde se ensayan las "
			 "escrituras de F2/F3. La conexión de producción se mantiene read-only a "
			 "nivel GitHub como red de seguridad dura, además del código.")

	repository_ids = fields.One2many("repo.repository", "backend_id", string="Repositorios")
	repository_count = fields.Integer(string="Repos", compute="_compute_repository_count")

	_login_uniq = models.Constraint(
		"UNIQUE (provider, owner_login)",
		"Ya existe una conexión para esa cuenta en ese proveedor.")

	# ------------------------------------------------------------------
	# Secreto
	# ------------------------------------------------------------------

	def _compute_private_key(self):
		"""Nunca devuelve la clave. Es write-only: se carga y no se vuelve a ver."""
		for backend in self:
			backend.private_key = False

	def _inverse_private_key(self):
		for backend in self:
			if backend.private_key:
				backend.private_key_encrypted = backend._cifrar(backend.private_key)

	@api.depends("private_key_encrypted")
	def _compute_private_key_set(self):
		for backend in self:
			backend.private_key_set = bool(backend.private_key_encrypted)

	def _fernet(self):
		"""Fernet (AES-128-CBC + HMAC-SHA256) con clave derivada de un secreto de odoo.conf.

		POR QUÉ NO `database.secret`: ese parámetro vive en `ir_config_parameter`, o sea
		DENTRO de la base. Un `pg_dump` se lleva el texto cifrado y el material de la clave
		juntos, y descifrar es trivial. Comprobado, no supuesto.

		La clave sale de `repo_manager_key` en odoo.conf, que no viaja en el dump. Un backup
		robado sin el archivo de configuración no sirve para nada.

		Y si el parámetro no está, esto NO cae a otra fuente peor: falla y lo dice. Un
		default silencioso acá significa creer que algo está cifrado cuando no lo está,
		que es peor que no cifrarlo.
		"""
		from cryptography.fernet import Fernet
		from odoo.tools import config

		secreto = config.get("repo_manager_key") or ""
		if len(secreto.strip()) < 32:
			raise UserError(_(
				"Falta `repo_manager_key` en odoo.conf, o es demasiado corta (mínimo 32 "
				"caracteres).\n\n"
				"La private key de la GitHub App se guarda cifrada con una clave derivada "
				"de ese secreto. Se lee del archivo de configuración a propósito: si la "
				"clave saliera de la base, un dump alcanzaría para descifrarla.\n\n"
				"Generá una con: openssl rand -base64 48"))
		clave = base64.urlsafe_b64encode(
			hashlib.sha256(("repo_manager:%s" % secreto).encode()).digest())
		return Fernet(clave)

	def _cifrar(self, texto):
		return self._fernet().encrypt(texto.encode()).decode()

	def _descifrar(self):
		"""PEM en claro, sólo en memoria y sólo para firmar el JWT."""
		self.ensure_one()
		if not self.private_key_encrypted:
			raise UserError(_("La conexión «%s» no tiene private key cargada.") % self.name)
		from cryptography.fernet import InvalidToken

		try:
			return self._fernet().decrypt(self.private_key_encrypted.encode()).decode()
		except InvalidToken as exc:
			# Error accionable, no un traceback de Fernet: el que lo lee tiene que saber
			# qué hacer sin abrir el código.
			raise UserError(_(
				"La private key cifrada de «%(nombre)s» no se puede descifrar con el "
				"secreto actual.\n\n"
				"Pasa cuando la base se restauró en otro servidor cuyo odoo.conf tiene "
				"otra `repo_manager_key`, o cuando alguien rotó ese secreto sin recifrar.\n\n"
				"Tenés dos salidas:\n"
				"• Poné en odoo.conf la misma `repo_manager_key` que tenía el servidor de "
				"origen, y si querés cambiarla usá «Rotar secreto de cifrado».\n"
				"• O volvé a cargar el .pem de la GitHub App en esta conexión.\n\n"
				"El backup de la base y el respaldo de `repo_manager_key` van juntos: uno "
				"sin el otro no sirve."
			) % {"nombre": self.name}) from exc

	# ------------------------------------------------------------------
	# Cliente
	# ------------------------------------------------------------------

	def client(self, transport=None):
		"""Cliente de LECTURA autenticado como la App. Ver github_client."""
		self.ensure_one()
		if not self.app_id or not self.installation_id:
			raise UserError(_(
				"Falta App ID o Installation ID en «%s». El Installation ID está en la "
				"URL de la app instalada: termina en /installations/<número>."
			) % self.name)
		auth = GithubAppAuth(
			self.app_id, self.installation_id, self._descifrar(), transport=transport)
		return GithubReadClient(auth.token, transport=transport)

	def write_client(self, transport=None):
		"""Cliente de ESCRITURA. Única puerta de entrada, y sólo para sandbox.

		LA COMPUERTA ES DURA Y NO TIENE INTERRUPTOR. Un parámetro de configuración para
		habilitar escrituras en producción sería exactamente el tipo de salvaguarda que
		alguien apaga un martes para destrabar algo. Para escribir sobre la conexión real
		hay que EDITAR ESTE MÉTODO, y eso es un cambio visible en un diff, revisable, y
		que obliga a decir en el commit que el criterio de salida se cumplió.

		Mientras tanto: si el backend no es sandbox, no hay cliente de escritura.
		"""
		self.ensure_one()
		if self.environment != "sandbox":
			raise UserError(_(
				"«%(nombre)s» es una conexión de entorno «%(entorno)s» y las escrituras "
				"sobre GitHub están cerradas ahí.\n\n"
				"La gobernanza se aplica primero sobre la organización de pruebas, y la "
				"conexión de producción se mantiene de sólo lectura hasta que el criterio "
				"de salida del banco de pruebas esté cumplido y revisado.\n\n"
				"No hay una opción de configuración para saltear esto a propósito: "
				"habilitarlo es un cambio de código."
			) % {"nombre": self.name, "entorno": self.environment})

		from .github_write_client import GithubWriteClient

		if not self.app_id or not self.installation_id:
			raise UserError(_(
				"Falta App ID o Installation ID en «%s».") % self.name)
		auth = GithubAppAuth(
			self.app_id, self.installation_id, self._descifrar(), transport=transport)
		return GithubWriteClient(auth.token, transport=transport)

	# ------------------------------------------------------------------
	# Acciones
	# ------------------------------------------------------------------

	def action_test_connection(self):
		"""Única llamada HTTP en el hilo del usuario, y a propósito: sin esto no hay
		forma de saber si la credencial sirve antes de encolar una auditoría entera."""
		self.ensure_one()
		try:
			client = self.client()
			cuenta = client.get("/users/%s" % self.owner_login)
			tipo = (cuenta or {}).get("type", "")
			esperado = "Organization" if self.owner_type == "organization" else "User"
			if tipo and tipo != esperado:
				# No se corrige solo: el tipo cambia los endpoints y prefiero que lo
				# decida una persona antes de recorrer 94 repos por el camino equivocado.
				raise UserError(_(
					"La cuenta «%(login)s» es de tipo %(real)s en GitHub, pero acá está "
					"configurada como %(config)s. Corregí el tipo de cuenta: cambia los "
					"endpoints que se consultan."
				) % {"login": self.owner_login, "real": tipo, "config": esperado})
			self.write({
				"state": "connected",
				"last_error": False,
				"rate_remaining": client.last_rate_remaining or 0,
			})
			self.message_post(body=_(
				"Conexión verificada contra %(login)s (%(tipo)s). Cuota restante: %(cuota)s."
			) % {"login": self.owner_login, "tipo": tipo or "?",
				 "cuota": client.last_rate_remaining})
		except (GithubError, UserError) as exc:
			self.write({"state": "error", "last_error": str(exc)})
			raise
		except Exception as exc:  # noqa: BLE001 - cualquier otra cosa también se muestra
			_logger.exception("Repo Manager: falló la prueba de conexión de %s", self.name)
			self.write({"state": "error", "last_error": str(exc)})
			raise UserError(_("No pude conectar: %s") % exc) from exc
		return True

	@api.depends("repository_ids")
	def _compute_repository_count(self):
		for backend in self:
			backend.repository_count = len(backend.repository_ids)
