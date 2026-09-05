/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * La bitácora como línea de tiempo, abierta en un navegador de verdad.
 *
 * POR QUÉ ESTE TOUR EXISTE. Los tres defectos que tuvo esta pantalla en su primera corrida
 * no se ven desde el servidor y no los agarra ningún test de modelo: el texto salía gris
 * clarito porque la vista lista de Odoo apaga su cuerpo; «Lo hizo» salía vacío porque en
 * Odoo 19 un many2one llega como objeto y no como par; y el subtítulo, metido dentro de la
 * grilla, le robó la primera columna y empujó la línea de tiempo a los 300 px del costado.
 * Los tres cargaban sin un solo error. Un test que no abre la pantalla no prueba la
 * pantalla.
 *
 * QUÉ COMPRUEBA, entonces: que el componente reemplace el cuerpo de la lista, que la
 * grilla tenga sus dos columnas, que el antes/después se abra, y que el casillero apagado
 * esté visible y no se pueda apretar — que es la regla 2 del proceso visual, y si se
 * puede apretar dejó de estar apagada.
 */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("prm_bitacora", {
	url: "/odoo/action-primate_repo_manager.action_repo_audit_log",
	steps: () => [
		{
			trigger: ".rm-bitacora .rm-bitacora-fila",
			content: "la línea de tiempo reemplazó el cuerpo de la lista",
		},
		{
			// La búsqueda de Odoo tiene que seguir estando: lo que el diseño cambia es
			// cómo se lee cada entrada, no cómo se la busca.
			trigger: ".o_searchview",
			content: "el panel de control nativo sigue ahí",
		},
		{
			trigger: ".rm-bitacora-cuerpo",
			content: "la grilla tiene sus dos columnas y la línea NO está en la angosta",
			run() {
				const cuerpo = document.querySelector(".rm-bitacora-cuerpo");
				const linea = document.querySelector(".rm-bitacora-linea");
				if (linea.getBoundingClientRect().width < cuerpo.getBoundingClientRect().width / 2) {
					throw new Error(
						"la línea de tiempo quedó en la columna angosta: la grilla tiene " +
						"más hijos de los que su plantilla declara");
				}
			},
		},
		{
			trigger: ".rm-bitacora-tarjeta .rm-bitacora-frase",
			content: "cada entrada dice en castellano qué pasó",
			run() {
				const frase = document.querySelector(".rm-bitacora-frase");
				if (!frase.textContent.trim()) {
					throw new Error("la frase de la entrada está vacía");
				}
			},
		},
		{
			trigger: ".rm-bitacora-leyenda-item:nth-child(5)",
			content: "la leyenda tiene los cuatro tipos (el primer hijo es el título)",
		},
		{
			trigger: ".rm-bitacora-mas",
			content: "se abre el antes/después",
			run: "click",
		},
		{
			trigger: ".rm-antes-despues .rm-ad-antes .rm-ad-cuerpo, .rm-antes-despues .rm-ad-antes .rm-no-legible",
			content: "el «antes» muestra su contenido, o DICE que no lo tiene",
		},
		{
			trigger: ".rm-apagado",
			content: "lo que todavía no llegó se ve y no se toca",
			run() {
				const apagado = document.querySelector(".rm-apagado");
				if (!apagado.textContent.includes("llega con")) {
					throw new Error(
						"el casillero apagado no dice con qué bloque llega");
				}
				if (getComputedStyle(apagado).pointerEvents !== "none") {
					throw new Error(
						"el casillero apagado se puede apretar: dejó de estar apagado");
				}
			},
		},
	],
});
