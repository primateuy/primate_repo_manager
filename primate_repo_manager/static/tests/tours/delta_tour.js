/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * La pantalla del delta, recorrida en un navegador — página 2b.
 *
 * Lo que este tour existe para vigilar es el TERCER BLOQUE. Los dos primeros —nuevos y
 * resueltos— se rompen de forma visible: si desaparecen, la pantalla queda vacía y se
 * nota. «Sin confirmar» no: si un día deja de dibujarse, la pantalla sigue viéndose
 * perfecta y lo único que pasa es que el módulo empieza a decir que se resolvieron cosas
 * que nadie miró. Eso no se nota mirando.
 */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("prm_delta", {
	steps: () => [
		{
			content: "la corrida abre con su delta",
			trigger: ".rm-delta .rm-delta-titulo:contains(Qué cambió)",
		},
		{
			content: "la frase dice en castellano qué pasó",
			trigger: ".rm-delta-frase:contains(Aparecieron)",
		},
		{
			content: "el bloque de nuevos, con su severidad",
			trigger: ".rm-delta-bloque-titulo:contains(Nuevos)",
		},
		{
			trigger: ".rm-delta .rm-chip-critical",
		},
		{
			content: "el bloque de resueltos",
			trigger: ".rm-delta-bloque-titulo:contains(Resueltos)",
		},
		{
			// EL PASO QUE MÁS IMPORTA.
			content: "«sin confirmar», con el repositorio que no se pudo leer",
			trigger: ".rm-delta-sin-confirmar .rm-no-legible:contains(sbx-caido)",
		},
		{
			content: "y con el MOTIVO al lado, que es lo que dice cómo se resuelve",
			trigger: ".rm-delta-sin-confirmar .rm-delta-nota:contains(403)",
		},
		{
			content: "dice explícitamente que no cuentan como resueltos ni como nuevos",
			trigger: ".rm-delta-sin-confirmar p:contains(No cuentan como resueltos)",
		},
		{
			content: "el botón arma un plan y lo dice: no escribe nada",
			trigger: ".rm-delta-acciones .rm-delta-nota:contains(No escribe nada en GitHub)",
		},
		{
			content: "y arma el plan",
			trigger: ".rm-delta-acciones button:contains(Armar plan)",
			run: "click",
		},
		{
			// El plan se abre en BORRADOR. Es lo que hace verdadera la frase del botón:
			// arma y no ejecuta. El estado va en la barra de estado del formulario.
			content: "que abre en BORRADOR, sin haber aplicado nada",
			trigger: ".o_form_view .o_statusbar_status button.o_arrow_button_current:contains(Borrador)",
		},
	],
});
