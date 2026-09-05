"""Abre TODAS las entradas del menú y falla si alguna tira un error de cliente.

Existe por un defecto que ningún test vio: un `context` con literales partidos en varias
líneas es Python válido pero el evaluador del navegador no lo entiende. El módulo cargaba
perfecto y la pantalla reventaba recién al hacer clic.
"""
import base64, json, os, shutil, subprocess, sys, tempfile, time, urllib.request
import websocket

BASE, BD = "http://localhost:8069", "o19_primate_stg_12082026"
LOGIN, PASS = "capturas", "capturas-2026"
PERFIL = tempfile.mkdtemp(prefix="prm-menu-")
proc = subprocess.Popen([
	"/Applications/Chromium.app/Contents/MacOS/Chromium", "--headless=new",
	"--disable-gpu", "--no-first-run", "--no-sandbox", "--remote-allow-origins=*",
	"--remote-debugging-port=9555", "--window-size=1500,950",
	"--user-data-dir=%s" % PERFIL, "about:blank"],
	stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
	for _ in range(60):
		try:
			pagina = [t for t in json.loads(urllib.request.urlopen(
				"http://localhost:9555/json").read()) if t["type"] == "page"][0]
			break
		except Exception:
			time.sleep(0.5)
	ws = websocket.create_connection(pagina["webSocketDebuggerUrl"], max_size=40*1024*1024)
	n = [0]
	def cdp(m, **p):
		n[0] += 1
		ws.send(json.dumps({"id": n[0], "method": m, "params": p}))
		while True:
			msg = json.loads(ws.recv())
			if msg.get("id") == n[0]:
				return msg.get("result", {})
	def js(e):
		r = cdp("Runtime.evaluate", expression=e, returnByValue=True, awaitPromise=True)
		return (r.get("result") or {}).get("value")
	cdp("Page.enable"); cdp("Runtime.enable")
	cdp("Page.navigate", url=BASE + "/web/login"); time.sleep(3)
	js("""fetch('/web/session/authenticate',{method:'POST',headers:{'Content-Type':'application/json'},
		body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{db:'%s',login:'%s',password:'%s'}})})
		.then(r=>r.json())""" % (BD, LOGIN, PASS))

	ACCIONES = ["panel", "promocion_modulos", "promocion_ramas", "prs", "rama_tarea",
				"crear_repo", "seguridad", "higiene", "forks", "notificaciones"]
	malas = []
	for clave in ACCIONES:
		url = "%s/odoo/action-primate_repo_manager.action_pendiente_%s" % (BASE, clave)
		cdp("Page.navigate", url=url)
		ok = False
		for _ in range(25):
			time.sleep(0.6)
			if js("!!document.querySelector('.rm-pendiente')"):
				ok = True; break
			if js("!!document.querySelector('.o_error_dialog, .modal-title')"):
				break
		titulo = js("(document.querySelector('.rm-pendiente h1')||{}).innerText") or ""
		error = js("(document.querySelector('.o_error_dialog, .modal-body')||{}).innerText") or ""
		print("%-20s %s  %s" % (clave, "OK " if ok else "ROTA", (titulo or error)[:70].replace("\n"," ")))
		if not ok:
			malas.append(clave)
	# Y las reales, de paso.
	for clave, sel in (("action_repo_module", ".o_list_view"),
					   ("action_repo_audit_finding", ".o_list_view"),
					   ("action_repo_repository", ".o_list_view")):
		cdp("Page.navigate", url="%s/odoo/action-primate_repo_manager.%s" % (BASE, clave))
		ok = False
		for _ in range(25):
			time.sleep(0.6)
			if js("!!document.querySelector('%s')" % sel):
				ok = True; break
		print("%-20s %s" % (clave, "OK" if ok else "ROTA"))
		if not ok:
			malas.append(clave)
	print("\nROTAS:", malas or "ninguna")
finally:
	proc.terminate(); shutil.rmtree(PERFIL, ignore_errors=True)
