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

	# ------------------------------------------------------------------
	# Credenciales de ESCRITURA — una App distinta, a propósito
	# ------------------------------------------------------------------
	#
	# La App de auditoría queda de sólo lectura PARA SIEMPRE. La escritura entra por una
	# segunda App con su propia instalación, y esa separación no es organizativa: es lo
	# que hace que el camino de lectura no PUEDA escribir aunque alguien se equivoque de
	# método. `client()` usa una credencial; `write_client()` usa la otra, y no hay
	# ninguna forma de que la primera adquiera verbos de escritura.
	#
	# Además permite lo que la de auditoría no puede permitirse: instalarla sobre un
	# SUBCONJUNTO de repositorios. La auditoría necesita verlo todo o su informe miente;
	# la escritura no, y acotarla por instalación pone un límite que GitHub hace cumplir,
	# fuera del alcance de cualquier bug del módulo.

	write_app_id = fields.Char(string="App ID de escritura", tracking=True)
	write_installation_id = fields.Char(
		string="Installation ID de escritura", tracking=True)
	write_private_key = fields.Text(
		string="Private key de escritura (PEM)", compute="_compute_write_private_key",
		inverse="_inverse_write_private_key", store=False)
	write_private_key_encrypted = fields.Text(
		string="Private key de escritura cifrada", copy=False)
	write_key_set = fields.Boolean(
		string="Clave de escritura cargada", compute="_compute_write_key_set",
		store=True)

	def _compute_write_private_key(self):
		for backend in self:
			backend.write_private_key = False

	def _inverse_write_private_key(self):
		for backend in self:
			if backend.write_private_key:
				backend.write_private_key_encrypted = backend._cifrar(
					backend.write_private_key)

	@api.depends("write_private_key_encrypted")
	def _compute_write_key_set(self):
		for backend in self:
			backend.write_key_set = bool(backend.write_private_key_encrypted)

	def _descifrar_escritura(self):
		self.ensure_one()
		if not self.write_private_key_encrypted:
			raise UserError(_(
				"La conexión «%s» no tiene cargada la private key de la App de "
				"escritura.") % self.name)
		from cryptography.fernet import InvalidToken

		try:
			return self._fernet().decrypt(
				self.write_private_key_encrypted.encode()).decode()
		except InvalidToken as exc:
			raise UserError(_(
				"La private key de escritura de «%s» no se puede descifrar con el "
				"secreto actual. Ver «Rotar secreto de cifrado»." ) % self.name) from exc

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

	# --- A7: la habilitación explícita de escritura en producción ---------
	#
	# Durante toda la F2, `write_client()` rechazaba cualquier escritura desde una conexión
	# de producción, sin excepción. Esa compuerta se quitó al pasar a la arquitectura de
	# dos Apps, y el reemplazo —el alcance de la instalación— acota el radio del daño pero
	# NO exige un acto deliberado: cargar las credenciales alcanzaba, y el primer apply
	# real salió sin ninguna confirmación adicional.
	#
	# Esto es ese acto. No agrega capacidad: protege la que ya existe.
	write_enabled = fields.Boolean(
		string="Escritura habilitada", default=False, copy=False, readonly=True,
		help="Sobre una conexión de producción, además de las credenciales hace falta "
			 "esta habilitación explícita. Se activa desde el botón, no editando el "
			 "campo, y queda registrada en la bitácora.")
	write_enabled_by_id = fields.Many2one(
		"res.users", string="Habilitada por", readonly=True, copy=False,
		ondelete="set null")
	write_enabled_at = fields.Datetime(
		string="Habilitada el", readonly=True, copy=False)

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
		"""Cliente de ESCRITURA. Única puerta, y con dos condiciones.

		LA PRIMERA ES ESTRUCTURAL: hace falta una App de escritura configurada. Sin sus
		credenciales no hay cliente, y punto — la App de auditoría no sirve para esto ni
		aunque alguien la pase por acá, porque sus permisos son de lectura y GitHub la
		frena del otro lado. Es la compuerta más fuerte que tenemos: no depende de un
		campo de Odoo que alguien pueda editar.

		LA SEGUNDA ES DE ENTORNO, y ya no es un «nunca» sino un «no sin decirlo». Sobre una
		conexión de producción se exige además la habilitación explícita —ver
		`write_enabled`—, que es un acto deliberado y registrado, no una consecuencia de
		haber cargado unas credenciales.

		Y sigue en pie lo que hace cumplir GitHub del otro lado: la App de escritura se
		instala SÓLO sobre los repositorios de la tanda en curso. El alcance de la
		instalación es el límite duro; la habilitación es el que obliga a mirarlo.
		"""
		self.ensure_one()
		# EL ORDEN IMPORTA, y lo destapó un test viejo que se puso rojo. Primero lo
		# estructural: si no hay App de escritura, decir «habilitá la escritura» manda a
		# alguien a habilitar algo que después va a fallar igual, por otro motivo. El
		# mensaje que se ve tiene que ser el del problema que hay que resolver primero.
		if not (self.write_app_id and self.write_installation_id
				and self.write_private_key_encrypted):
			raise UserError(_(
				"«%(nombre)s» no tiene configurada una App de escritura, así que no hay "
				"forma de escribir sobre GitHub desde esta conexión.\n\n"
				"La App de auditoría es de sólo lectura de forma permanente y no se usa "
				"para esto. La escritura entra por una App aparte, con su propia "
				"instalación y su propio alcance."
			) % {"nombre": self.name})
		if self.environment == "production" and not self.write_enabled:
			raise UserError(_(
				"«%(nombre)s» es una conexión de PRODUCCIÓN y no tiene la escritura "
				"habilitada.\n\n"
				"Tener credenciales cargadas no alcanza: hace falta un acto deliberado, "
				"que además queda registrado en la bitácora con quién y cuándo. Se "
				"habilita desde el botón «Habilitar escritura» del formulario de la "
				"conexión, después de mirar qué repositorios abarca la instalación."
			) % {"nombre": self.name})

		return self._construir_cliente_de_escritura(transport=transport)

	def _construir_cliente_de_escritura(self, transport=None):
		"""EL ÚNICO lugar del módulo donde se instancia `GithubWriteClient`.

		Está separado de `write_client` para que las guardas de aquél vivan en un lado y
		la construcción en otro, y para que siga habiendo una sola construcción cuando
		otro método necesite el cliente con otras condiciones —hoy,
		`_alcance_para_confirmar`, que lo usa sólo para leer—. Hay un test que recorre el
		árbol y falla si aparece una segunda.
		"""
		self.ensure_one()
		from .github_write_client import GithubWriteClient

		auth = GithubAppAuth(
			self.write_app_id, self.write_installation_id,
			self._descifrar_escritura(), transport=transport)
		return GithubWriteClient(auth.token, transport=transport)

	# ------------------------------------------------------------------
	# Habilitación de escritura
	# ------------------------------------------------------------------

	# La bandera con la que los métodos sancionados se identifican al tocar `write_enabled`.
	POR_LA_PUERTA = "repo_habilitacion_deliberada"

	def write(self, vals):
		"""`write_enabled` no se edita: se habilita por la puerta que deja rastro.

		Sin esto, todo el mecanismo se saltea con un `write({'write_enabled': True})` desde
		cualquier lado —una vista modificada, otro addon, la shell— y la entrada de
		bitácora nunca ocurre. El campo es `readonly` en la vista, pero readonly es
		presentación: no impide nada del lado del servidor.

		El default es NEGAR, al revés que en la clasificación de repositorios, y por la
		misma razón que allá era al revés: acá el olvido de un desarrollador futuro se
		paga con una habilitación sin rastro sobre producción. Que falle ruidosamente es
		exactamente lo que se quiere.
		"""
		if "write_enabled" in vals and not self.env.context.get(self.POR_LA_PUERTA):
			raise UserError(_(
				"La habilitación de escritura no se edita como un campo cualquiera.\n\n"
				"Se activa con «Habilitar escritura» y se apaga con «Deshabilitar», que "
				"es lo que deja la entrada en la bitácora. Un flag que se pueda poner en "
				"true sin dejar rastro no protege de nada."))
		return super().write(vals)

	def action_enable_writes(self):
		"""Abre la confirmación. Habilitar es una decisión, no una casilla."""
		self.ensure_one()
		return {
			"type": "ir.actions.act_window",
			"name": _("Habilitar escritura sobre «%s»") % self.name,
			"res_model": "repo.write.enable.wizard",
			"view_mode": "form",
			"target": "new",
			"context": {"default_backend_id": self.id},
		}

	def _habilitar_escritura(self, alcance=None):
		"""Lo hace el asistente, después de que una persona confirmó."""
		self.ensure_one()
		self.with_context(**{self.POR_LA_PUERTA: True}).write({
			"write_enabled": True,
			"write_enabled_by_id": self.env.user.id,
			"write_enabled_at": fields.Datetime.now(),
		})
		self.env["repo.audit.log"].registrar(
			"write_enabled",
			_("Escritura HABILITADA sobre «%(nombre)s» (%(entorno)s)") % {
				"nombre": self.name,
				"entorno": dict(self._fields["environment"].selection)[self.environment],
			},
			backend=self,
			payload={
				"entorno": self.environment,
				"write_app_id": self.write_app_id,
				"write_installation_id": self.write_installation_id,
				# Qué abarcaba la instalación EN ESE MOMENTO. Si mañana alguien la amplía,
				# la entrada sigue diciendo sobre qué se habilitó, que es la pregunta que
				# se hace después de un incidente.
				"alcance": sorted(alcance) if alcance else None,
			})
		return True

	def action_disable_writes(self):
		"""Apagar nunca es peligroso, así que no pide confirmación. Pero se registra."""
		self.ensure_one()
		if not self.write_enabled:
			return True
		self.with_context(**{self.POR_LA_PUERTA: True}).write({
			"write_enabled": False,
			"write_enabled_by_id": False,
			"write_enabled_at": False,
		})
		self.env["repo.audit.log"].registrar(
			"write_disabled",
			_("Escritura deshabilitada sobre «%s»") % self.name, backend=self)
		return True

	def _alcance_para_confirmar(self, transport=None):
		"""El alcance de la instalación, PARA MOSTRARLO antes de habilitar.

		Existe aparte de `alcance_de_escritura` por una razón de orden y no de permisos:
		aquél pasa por `write_client`, que sobre producción se niega mientras la escritura
		no esté habilitada — o sea, justo en el momento en que hace falta mirar el alcance
		para decidir si habilitarla. Esto es un huevo y su gallina, y se resuelve leyendo
		acá sin pedirle permiso a la puerta.

		Sólo LEE. El cliente que arma es el mismo, pero la única llamada que sale es el
		listado de la instalación.
		"""
		self.ensure_one()
		if not (self.write_app_id and self.write_installation_id
				and self.write_private_key_encrypted):
			raise UserError(_(
				"«%s» no tiene configurada una App de escritura: no hay instalación cuyo "
				"alcance mirar, ni escritura que habilitar.") % self.name)
		cliente = self._construir_cliente_de_escritura(transport=transport)
		datos = cliente.paginate(
			"/installation/repositories", envoltorio="repositories")
		return {r.get("full_name") for r in datos}

	def alcance_de_escritura(self, transport=None):
		"""Los repositorios que la App de escritura puede tocar, según GitHub.

		Se pregunta, no se supone. Es lo que permite decirle a alguien «este plan toca un
		repositorio fuera del alcance de la instalación» ANTES de empezar a escribir, en
		vez de que se entere con un 404 a mitad de camino y con parte del plan aplicado.
		"""
		self.ensure_one()
		cliente = self.write_client(transport=transport)
		datos = cliente.paginate(
			"/installation/repositories", envoltorio="repositories")
		return {r.get("full_name") for r in datos}

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
