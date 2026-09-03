/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * Política y personas, recorridas en un navegador.
 *
 * Dos caminos, y en los dos lo que se comprueba es la consecuencia y no el click:
 *
 * · PLANTILLA → QUÉ GOBIERNA → CAMBIAR UN UMBRAL → VERLO EN LA BITÁCORA. Que el cambio
 *   quede registrado se prueba en Python; acá se prueba que se pueda LLEGAR a la entrada
 *   desde la aplicación, que es lo que la vuelve útil. Un registro al que sólo se llega
 *   por consola es un registro que nadie va a mirar.
 *
 * · VINCULAR UNA CUENTA CON UN EMPLEADO. El asistente propone y una persona confirma; se
 *   comprueba que el aviso de «cuenta sin persona asociada» desaparece de la pantalla en
 *   cuanto queda vinculada.
 */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("prm_politica", {
	steps: () => [
		{
			content: "abrir la plantilla",
			trigger: ".o_list_view td[name=name]:contains(Plantilla del tour)",
			run: "click",
		},
		{
			content: "y avisa qué significa tocarla, antes y no después",
			trigger: ".alert:contains(no toca ningún repositorio)",
		},
		{
			// Cuántos gobierna se prueba en Python —el número depende de lo que haya en la
			// base—; lo que se prueba acá es que desde la plantilla se LLEGUE a ellos.
			content: "la plantilla lleva a los repositorios que gobierna",
			trigger: "button[name=action_open_repositories]",
			run: "click",
		},
		{
			trigger: ".o_list_view td:contains(sbx-int-0)",
		},
		{
			content: "volver a la plantilla",
			trigger: ".breadcrumb a:contains(Plantilla del tour)",
			run: "click",
		},
		{
			content: "bajar una exigencia",
			trigger: ".o_field_widget[name=required_approvals] input",
			run: "edit 1",
		},
		{
			content: "guardar",
			trigger: ".o_form_button_save",
			run: "click",
		},
		{
			content: "abrir la Bitácora desde el menú, como lo haría una persona",
			trigger: ".o_main_navbar button:contains(Bitácora), .o_main_navbar a:contains(Bitácora)",
			run: "click",
		},
		{
			content: "EL CAMBIO DE POLÍTICA ESTÁ EN LA BITÁCORA, y se llega desde la app",
			trigger: ".o_list_view td:contains(Plantilla del tour)",
		},
	],
});

registry.category("web_tour.tours").add("prm_personas", {
	steps: () => [
		{
			content: "abrir la cuenta sin persona asociada",
			trigger: ".o_list_view td[name=github_login]:contains(sin-duenio)",
			run: "click",
		},
		{
			content: "la pantalla dice el problema donde se resuelve",
			trigger: ".alert-warning:contains(no está vinculada a ninguna persona)",
		},
		{
			content: "preguntar quién es",
			trigger: "button[name=action_link_employee]",
			run: "click",
		},
		{
			content: "el asistente aclara que las coincidencias son pistas, no pruebas",
			trigger: ".modal .alert:contains(pistas, no pruebas)",
		},
		{
			content: "elegir a la persona",
			trigger: ".modal .o_field_widget[name=employee_id] input",
			run: "edit Empleado",
		},
		{
			trigger: ".modal .o-autocomplete--dropdown-item:not(:contains(Crear)):first",
			run: "click",
		},
		{
			content: "confirmar",
			trigger: ".modal button[name=action_confirm]",
			run: "click",
		},
		{
			content: "y el aviso desaparece porque el problema se resolvió",
			trigger: ".o_form_view:not(:has(.alert-warning:contains(no está vinculada)))",
		},
	],
});
