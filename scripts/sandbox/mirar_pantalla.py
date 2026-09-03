#!/usr/bin/env python3
# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Abre la pantalla en un Chromium de verdad, aprieta Auditar y anota qué se ve.

POR QUÉ EXISTE. El componente de avance en vivo se dio por bueno una vez razonando sobre
el código —el bus emitía, los tests del servidor pasaban, el bundle compilaba— y en
pantalla no aparecía absolutamente nada. Los dos defectos eran de montaje: el componente
copiaba el registro en `setup()`, que corre una sola vez, y se suscribía al canal con el
id que el registro tenía en ese momento, que en un formulario nuevo todavía no existe.
Ninguna de las dos cosas se ve desde el servidor. De ahí la regla: una pantalla se
verifica abriéndola.

QUÉ HACE. Levanta Chromium sin ventana, entra por la API de sesión, abre la corrida,
aprieta «Auditar» y va anotando cada cambio del bloque `.o_prm_live` y de la clase y el
ancho de la barra. Guarda dos capturas: la del ámbar en marcha y la del cierre.

USO
    python3 mirar_pantalla.py <login> <password> <id de corrida>

Requiere `websocket-client` y Chromium en /Applications. Es una herramienta de
verificación, no producto: no la corre nadie salvo quien esté comprobando la pantalla.
"""
import json, os, shutil, subprocess, sys, tempfile, time, urllib.request
import websocket

BASE = "http://localhost:8069"
BD = os.environ.get("PRM_BD", "o19_primate_stg_12082026")
LOGIN, PASS, CORRIDA = sys.argv[1], sys.argv[2], int(sys.argv[3])
PERFIL = tempfile.mkdtemp(prefix="prm-chrome-")
CHROME = "/Applications/Chromium.app/Contents/MacOS/Chromium"
DESTINO = os.path.dirname(os.path.abspath(__file__))

proc = subprocess.Popen([
	CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-sandbox",
	"--remote-debugging-port=9333", "--window-size=1400,1000", "--remote-allow-origins=*",
	"--user-data-dir=%s" % PERFIL, "about:blank"],
	stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
	for _ in range(60):
		try:
			objetivos = json.loads(urllib.request.urlopen(
				"http://localhost:9333/json").read())
			pagina = [t for t in objetivos if t["type"] == "page"][0]
			break
		except Exception:
			time.sleep(0.5)
	else:
		raise SystemExit("Chromium no levantó")

	ws = websocket.create_connection(pagina["webSocketDebuggerUrl"],
									 max_size=20 * 1024 * 1024)
	n = [0]

	def cdp(metodo, **params):
		n[0] += 1
		ws.send(json.dumps({"id": n[0], "method": metodo, "params": params}))
		while True:
			msg = json.loads(ws.recv())
			if msg.get("id") == n[0]:
				if "error" in msg:
					raise SystemExit("CDP %s -> %s" % (metodo, msg["error"]))
				return msg.get("result", {})

	def js(expr, espera=True):
		r = cdp("Runtime.evaluate", expression=expr, awaitPromise=espera,
				returnByValue=True)
		return (r.get("result") or {}).get("value")

	cdp("Page.enable")
	cdp("Runtime.enable")

	# Login por la API, que es más estable que tipear en el formulario.
	cdp("Page.navigate", url=BASE + "/web/login")
	time.sleep(3)
	uid = js("""fetch('/web/session/authenticate', {method:'POST',
		headers:{'Content-Type':'application/json'},
		body: JSON.stringify({jsonrpc:'2.0', method:'call', params:
			{db:'%s', login:'%s', password:'%s'}})})
		.then(r=>r.json()).then(j=>(j.result&&j.result.uid)||('ERR '+JSON.stringify(j.error||j).slice(0,200)))
	""" % (BD, LOGIN, PASS))
	print("login ->", uid)

	url = "%s/odoo/action-primate_repo_manager.action_repo_audit_run/%s" % (BASE, CORRIDA)
	cdp("Page.navigate", url=url)
	for _ in range(60):
		time.sleep(1)
		if js("!!document.querySelector('.o_form_view')", espera=False):
			break
	time.sleep(3)

	print("componente en el DOM:", js("!!document.querySelector('.o_prm_live')", espera=False))
	print("texto inicial:", json.dumps(js(
		"(document.querySelector('.o_prm_live')||{}).innerText", espera=False)))

	apretado = js("""(() => {
		const b = [...document.querySelectorAll('button')]
			.find(x => x.textContent.trim() === 'Auditar');
		if (!b) return 'no encontré el botón';
		b.click(); return 'apretado';
	})()""", espera=False)
	print("botón Auditar:", apretado)

	print("\n--- lo que va mostrando la pantalla ---")
	visto, t0, ultimo = [], time.time(), None
	while time.time() - t0 < 150:
		txt = js("(document.querySelector('.o_prm_live')||{}).innerText", espera=False)
		clase = js("""(() => { const b =
			document.querySelector('.o_prm_barra_relleno');
			return b ? (b.className + ' | ' + b.style.width) : 'sin barra'; })()""",
			espera=False)
		firma = (txt, clase)
		if firma != ultimo:
			ultimo = firma
			visto.append(firma)
			print("[%5.1fs] barra: %s" % (time.time() - t0, clase))
			print("         %s" % (txt or "").replace("\n", " ⏐ "))
		if txt and "con error" in txt and "⚠ 0 con error" not in txt and "ambar" not in visto:
			visto.append("ambar")
			cap = cdp("Page.captureScreenshot", format="png")
			open(DESTINO + "/pantalla-ambar.png", "wb").write(
				__import__("base64").b64decode(cap["data"]))
			print("         >>> captura del ámbar guardada")
		if txt and ("Terminada" in txt):
			time.sleep(1)
			cap = cdp("Page.captureScreenshot", format="png")
			open(DESTINO + "/pantalla-final.png", "wb").write(
				__import__("base64").b64decode(cap["data"]))
			break
		time.sleep(1)

	print("\ncambios de pantalla observados:", len(visto))
finally:
	proc.terminate()
	shutil.rmtree(PERFIL, ignore_errors=True)
