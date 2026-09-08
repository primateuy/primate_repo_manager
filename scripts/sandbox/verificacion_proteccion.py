# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El falso «sin protección», verificado contra el sandbox REAL.

    ./odoo-bin shell -c <conf> -d <base> --no-http \
        < scripts/sandbox/verificacion_proteccion.py

QUÉ VINO A BUSCAR. El ensayo B5.4 dejó cinco hallazgos «rama sin protección» sobre un
repositorio recién nacido cuyas cuatro ramas habían quedado gobernadas por rulesets en
la misma corrida. La causa: el motor miraba `rama.protected`, que en GitHub responde
sólo por la protección clásica y NO por rulesets. Un repositorio gobernado enteramente
por rulesets —que es como los gobierna este módulo— salía marcado como desprotegido.

Esta verificación sincroniza de verdad contra prm-sandbox, corre la auditoría de verdad,
y cuenta. Es de sólo lectura salvo por el espejo propio.
"""
from odoo import fields

backend = env["repo.backend"].search([("environment", "=", "sandbox")], limit=1)
cliente = backend.client()

def titulo(t):
	print("\n" + "=" * 78); print(t); print("=" * 78)

titulo("1 · SINCRONIZANDO EL ESPEJO CONTRA prm-sandbox")
repos = backend.repository_ids
print("   repositorios: %s" % len(repos))
for repo in repos:
	repo._job_sync_repository(False)
env.cr.commit()
print("   rulesets propios en el espejo: %s"
	  % env["repo.ruleset"].search_count([("repository_id", "in", repos.ids)]))

titulo("2 · LO QUE EL COMPARADOR VE, RAMA POR RAMA")
for repo in repos.sorted("full_name"):
	for rama in repo.branch_ids.sorted("name"):
		c = rama.comparacion_de_politica()
		cubren = rama._rulesets_que_la_cubren()
		print("   %-34s %-14s protected=%-5s rulesets=%-2s -> %s"
			  % (repo.full_name, rama.name, rama.protected, len(cubren), c["estado"]))

titulo("3 · AUDITORÍA REAL")
corrida = env["repo.audit.run"].create({
	"name": "Verificación de protección", "backend_id": backend.id,
	"state": "done", "finished_at": fields.Datetime.now()})
env["repo.audit.engine"].evaluate(corrida)
env.cr.commit()
sin_prot = corrida.finding_ids.filtered(lambda f: f.finding_type == "branch_unprotected")
print("   hallazgos totales: %s" % len(corrida.finding_ids))
print("   «rama sin protección»: %s" % len(sin_prot))
for f in sin_prot:
	print("      - %s" % f.summary[:95])

titulo("4 · VEREDICTO")
gobernados = repos.filtered(lambda r: env["repo.ruleset"].search_count(
	[("repository_id", "=", r.id), ("state", "=", "present")]))
falsos = sin_prot.filtered(lambda f: f.repository_id in gobernados)
print("   repositorios gobernados por rulesets: %s" % len(gobernados))
print("   hallazgos de «sin protección» sobre ellos: %s" % len(falsos))
print("   %s" % ("[BIEN] ninguno: el falso positivo desapareció" if not falsos
				 else "[MAL] siguen apareciendo"))
