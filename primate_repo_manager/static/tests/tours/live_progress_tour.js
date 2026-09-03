/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * El componente de avance en vivo, recorrido en un navegador de verdad.
 *
 * POR QUÉ ESTE TOUR EXISTE Y NO ALCANZAN LOS TESTS DEL SERVIDOR. Los dos defectos que
 * dejaron la pantalla muda en el primer recorrido real —el estado copiado en `setup()`, la
 * suscripción atada al id que el registro tenía al montar— no se ven desde el servidor:
 * el bus emitía bien, los tests pasaban y el bundle compilaba. Un test que no abre la
 * pantalla no prueba la pantalla.
 *
 * POR QUÉ EL TOUR MANEJA EL RELOJ. Los estados intermedios son transitorios: la barra en
 * ámbar CON la corrida en marcha dura lo que dura el repositorio siguiente. Si el servidor
 * fuera emitiendo por su cuenta mientras el tour mira, cada paso sería una carrera y el
 * test fallaría cada tanto por motivos que no son el código. Acá el tour escribe los
 * contadores y pide `action_refresh_progress`, así que cada estado aparece cuando el paso
 * anterior ya se comprobó. Lo que se prueba es el camino entero de verdad —emitir, bus,
 * websocket, componente, DOM—; lo único que se le quita es el azar.
 */

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

/** Deja la corrida en un estado y hace que el servidor lo cuente por el bus. */
async function avanzar(valores) {
	// El id sale de la URL —`/odoo/action-.../<id>`— y no de una variable global que
	// alguien tenga que acordarse de poner: si el tour se abre en otra corrida, sigue
	// apuntando a la que está en pantalla.
	const id = parseInt(window.location.pathname.split("/").pop(), 10);
	if (valores) {
		await rpc("/web/dataset/call_kw", {
			model: "repo.audit.run", method: "write",
			args: [[id], valores], kwargs: {},
		});
	}
	await rpc("/web/dataset/call_kw", {
		model: "repo.audit.run", method: "action_refresh_progress",
		args: [[id]], kwargs: {},
	});
}

registry.category("web_tour.tours").add("prm_live_progress", {
	steps: () => [
		{
			content: "la corrida en curso se pinta con el bloque vivo, no con el estático",
			trigger: ".o_prm_live .o_prm_live_corriendo",
		},
		{
			content: "recién cargada, la pantalla se pinta con el registro: 0 de 3",
			trigger: ".o_prm_live_fraccion:contains(0 de 3)",
			async run() {
				// Todavía no llegó ningún aviso, así que no hay «Ahora:» que mostrar: el
				// registro no guarda qué repositorio se está recorriendo. Se le pide al
				// servidor que cuente, que es lo que hace el botón «Volver a preguntar».
				await avanzar(null);
			},
		},
		{
			content: "y ahora sí dice qué repositorio está recorriendo",
			trigger: ".o_prm_live_actual:contains(sbx-uno)",
			async run() {
				await avanzar({ repos_done: 1 });
			},
		},
		{
			trigger: ".o_prm_live_fraccion:contains(1 de 3)",
		},
		{
			content: "la barra acompaña al contador",
			trigger: ".o_prm_barra_relleno",
			async run() {
				// El caso feo: un repositorio falla y quedan otros por recorrer.
				await avanzar({ repos_error: 1 });
			},
		},
		{
			content: "LA BARRA SE TIÑE CON LA CORRIDA TODAVÍA EN MARCHA",
			trigger: ".o_prm_live_corriendo .o_prm_barra_relleno.o_prm_con_error",
		},
		{
			content: "y el contador de errores deja de estar apagado",
			trigger: ".o_prm_live_datos .o_prm_alerta:contains(1 con error)",
			async run() {
				await avanzar({ state: "partial", repos_done: 2 });
			},
		},
		{
			content: "al cerrar con errores lo dice, y no lo disimula",
			trigger: ".o_prm_live_fin.o_prm_fin_con_error:contains(Terminada con errores)",
		},
		{
			content: "el resumen trae los hallazgos que la corrida produjo",
			trigger: ".o_prm_live_fin .o_prm_live_fraccion:contains(2 hallazgos)",
		},
		{
			content: "y no deja pasar por revisado lo que no se revisó",
			trigger: ".o_prm_live_fin:contains(no se pudieron recorrer del todo)",
		},
		{
			content: "«Ver hallazgos» abre la lista de esta corrida",
			trigger: ".o_prm_live_fin button:contains(Ver hallazgos)",
			run: "click",
		},
		{
			content: "y la lista muestra el hallazgo, no una columna de ids",
			trigger: ".o_list_view td:contains(rama sin protección)",
		},
	],
});

/**
 * El caso que rompió: una corrida creada con «Nuevo».
 *
 * Es el recorrido exacto del primer intento fallido, y por eso vale como test aparte. Un
 * formulario abierto con «Nuevo» todavía no tiene id; el componente se monta ahí y no
 * tiene a qué canal suscribirse. Si la suscripción sólo se resuelve al montar —como estaba
 * al principio— al guardar aparece el id y nadie vuelve a mirar: la pantalla queda muda
 * para siempre.
 *
 * Lo que delata el defecto es «Ahora:», y no es casualidad: los contadores viajan en el
 * registro, así que una recarga los muestra igual y un componente mudo pasaría por sano.
 * El repositorio que se está recorriendo NO se guarda en ningún lado — sólo llega por el
 * bus. Si aparece en pantalla, el componente se suscribió después de guardar.
 */
registry.category("web_tour.tours").add("prm_live_progress_nuevo", {
	steps: () => [
		{
			content: "crear una corrida desde cero",
			trigger: ".o_list_button_add",
			run: "click",
		},
		{
			content: "elegir la conexión",
			trigger: ".o_field_widget[name=backend_id] input",
			run: "edit GitHub — tour",
		},
		{
			trigger: ".o-autocomplete--dropdown-item:contains(GitHub — tour)",
			run: "click",
		},
		{
			content: "guardar: recién acá el registro tiene id",
			trigger: ".o_form_button_save",
			run: "click",
		},
		{
			content: "sin ejecutar, la pantalla lo dice sin inventar una barra",
			trigger: ".o_prm_live_quieto:contains(Todavía no se ejecutó)",
			async run() {
				await avanzar({ state: "running", repos_total: 3, repos_done: 1 });
			},
		},
		{
			content: "y el aviso llega: el componente se suscribió DESPUÉS de guardar",
			trigger: ".o_prm_live_actual:contains(sbx-uno)",
		},
		{
			trigger: ".o_prm_live_fraccion:contains(1 de 3)",
		},
	],
});
