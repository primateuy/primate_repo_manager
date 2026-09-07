# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""B6.4 · las alertas de seguridad contra la cuenta REAL. Sólo lectura.

    ./odoo-bin shell -c <conf> -d <base> --no-http \
        < scripts/sandbox/verificacion_b64_seguridad.py

POR QUÉ CONTRA PRODUCCIÓN Y NO CONTRA EL SANDBOX. Los tres estados se midieron acá: el
sandbox no tiene alertas reales, y una verificación sobre datos sembrados por nosotros
sólo comprueba que sabemos sembrar. Es de SÓLO LECTURA —la App de auditoría no tiene un
solo permiso de escritura— así que no toca la frontera de producción.

QUÉ COMPRUEBA
  · los tres estados, contados sobre los 113 repositorios que la App alcanza;
  · que los cuatro públicos con alertas vivas se lean de verdad;
  · que NINGÚN secreto haya entrado al espejo — revisando todos los campos de texto;
  · que los hallazgos salgan con sus dos tratamientos.
"""
import collections

from odoo import fields

backend = env["repo.backend"].search([("owner_login", "=", "primateuy")], limit=1)
cliente = backend.client()

def titulo(texto):
	print("\n" + "=" * 78)
	print(texto)
	print("=" * 78)

titulo("LEYENDO LAS DOS FUENTES SOBRE LA CUENTA REAL (sólo lectura)")
repos = backend.repository_ids
print("   repositorios en el espejo: %s" % len(repos))
leidos = 0
for repo in repos:
	try:
		repo._sync_security_alerts(cliente)
		leidos += 1
	except Exception as exc:
		print("   [MAL] %s: %s" % (repo.full_name, str(exc)[:80]))
env.cr.commit()
print("   repositorios recorridos: %s" % leidos)

titulo("LOS TRES ESTADOS, CONTADOS")
Scan = env["repo.security.scan"]
conteo = collections.Counter()
for fila in Scan.search([("repository_id", "in", repos.ids)]):
	conteo["%s · %s" % (fila.source, fila.state)] += 1
for clave in sorted(conteo):
	print("   %-44s %s" % (clave, conteo[clave]))
print("\n   con Advanced Security como causa del apagado: %s" % Scan.search_count([
	("repository_id", "in", repos.ids), ("needs_advanced_security", "=", True)]))

titulo("LOS QUE SÍ SE PUDIERON LEER")
for fila in Scan.search([("repository_id", "in", repos.ids),
						 ("state", "=", "con_datos")]):
	print("   %-46s %-16s %s alerta(s) abiertas" % (
		fila.repository_id.full_name, fila.source, fila.alert_count))

titulo("EL SECRETO NO ENTRÓ — revisando TODOS los campos de texto del espejo")
Alerta = env["repo.security.alert"]
alertas = Alerta.search([("repository_id", "in", repos.ids)])
print("   alertas espejadas: %s" % len(alertas))
campos_texto = [c for c, f in Alerta._fields.items() if f.type in ("char", "text")]
print("   campos de texto del espejo: %s" % ", ".join(sorted(campos_texto)))
prohibidos = [c for c in Alerta.CAMPOS_PROHIBIDOS if c in Alerta._fields]
print("   campos prohibidos presentes: %s" % (prohibidos or "NINGUNO"))
sospechosos = []
for alerta in alertas:
	for campo in campos_texto:
		valor = alerta[campo] or ""
		# Las formas de secreto que GitHub detecta y que jamás deberían estar acá.
		for prefijo in ("ghp_", "gho_", "ghs_", "github_pat_", "AKIA", "-----BEGIN"):
			if prefijo in str(valor):
				sospechosos.append((alerta.id, campo, prefijo))
print("   valores con forma de secreto: %s" % (sospechosos or "NINGUNO"))

titulo("LOS HALLAZGOS, CON SUS DOS TRATAMIENTOS")
corrida = env["repo.audit.run"].create({
	"name": "Verificación B6.4", "backend_id": backend.id, "state": "done",
	"finished_at": fields.Datetime.now()})
env["repo.audit.engine"].evaluate(corrida)
env.cr.commit()
por_tipo = collections.Counter(corrida.finding_ids.mapped("finding_type"))
for tipo in ("secret_leaked", "dependency_vulnerabilities",
			 "security_feature_disabled"):
	print("   %-32s %s" % (tipo, por_tipo.get(tipo, 0)))

print("\n   un ejemplo de cada uno:")
for tipo in ("secret_leaked", "dependency_vulnerabilities",
			 "security_feature_disabled"):
	ejemplo = corrida.finding_ids.filtered(lambda h, t=tipo: h.finding_type == t)[:1]
	if ejemplo:
		print("\n   [%s] %s" % (ejemplo.severity.upper(), ejemplo.summary[:100]))
		print("      cómo se resuelve: %s" % ejemplo._remediation_label())
		print("      planificable: %s" % ejemplo.can_be_planned)
