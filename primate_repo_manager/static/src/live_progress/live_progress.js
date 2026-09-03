/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * Avance en vivo de una corrida de auditoría.
 *
 * POR QUÉ ESTE COMPONENTE EXISTE. Una vista estándar muestra el valor que tenía el
 * registro cuando se cargó la página. Para ver avanzar una auditoría había que refrescar
 * a mano, y eso no es usable: el usuario no puede saber si el trabajo avanza o murió.
 *
 * NO RECARGA EL REGISTRO MIENTRAS CORRE. Se pinta con lo que llega por el bus. Recargar en
 * cada repositorio haría parpadear el formulario entero para mover un número, y con
 * cientos de repositorios sería una recarga cada pocos segundos. La única recarga es al
 * terminar, una sola vez, para que el resto de la pantalla quede al día.
 *
 * DEGRADA DICIENDO LA VERDAD. Si no llegan avisos, no finge una barra que avanza ni se
 * queda muda: dice que hace rato que no recibe novedades y por qué puede pasar. Una
 * corrida lenta y una colgada se ven distinto.
 */

import { Component, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";

// Cuántos segundos sin novedades antes de avisar que algo puede estar mal. Tiene que ser
// holgado: un repositorio grande tarda más de diez segundos y no por eso está colgado.
const SILENCIO_SOSPECHOSO = 20;

export class LiveProgress extends Component {
    static template = "primate_repo_manager.LiveProgress";
    static props = { ...standardFieldProps };

    setup() {
        this.bus = useService("bus_service");
        this.action = useService("action");
        this.orm = useService("orm");

        const registro = this.props.record;
        this.state = useState({
            estado: registro.data.state,
            total: registro.data.repos_total || 0,
            hechos: registro.data.repos_done || 0,
            errores: registro.data.repos_error || 0,
            actual: null,
            hallazgos: 0,
            criticos: 0,
            altos: 0,
            segundos: 0,
            silencio: 0,
            recibioAlgo: false,
        });

        this.corridaId = registro.resId;
        this.canal = `repo.audit.run_${this.corridaId}`;
        this.yaRecargo = false;

        this._alRecibir = (payload) => this._recibir(payload);
        if (this.corridaId) {
            this.bus.addChannel(this.canal);
            this.bus.subscribe("repo_manager.audit_progress", this._alRecibir);
        }

        // Un solo reloj para el cronómetro y para detectar el silencio.
        this.reloj = setInterval(() => {
            if (this.state.estado === "running") {
                this.state.segundos += 1;
                this.state.silencio += 1;
            }
        }, 1000);

        onWillUnmount(() => {
            clearInterval(this.reloj);
            if (this.corridaId) {
                this.bus.unsubscribe("repo_manager.audit_progress", this._alRecibir);
                this.bus.deleteChannel(this.canal);
            }
        });
    }

    _recibir(payload) {
        // Llegan avisos de todas las corridas suscritas; sólo interesa la de esta pantalla.
        if (!payload || payload.id !== this.corridaId) {
            return;
        }
        this.state.recibioAlgo = true;
        this.state.silencio = 0;
        this.state.estado = payload.state;
        this.state.total = payload.total;
        this.state.hechos = payload.done;
        this.state.errores = payload.error;
        this.state.actual = payload.actual || this.state.actual;
        this.state.hallazgos = payload.findings;
        this.state.criticos = payload.criticos;
        this.state.altos = payload.altos;

        if (["done", "partial", "error"].includes(payload.state) && !this.yaRecargo) {
            // Una sola recarga, al final: el resto del formulario —fechas, chatter— tiene
            // que quedar al día, y esto ya no interrumpe nada porque terminó.
            this.yaRecargo = true;
            this.state.actual = null;
            this.props.record.load();
        }
    }

    get nombreCuenta() {
        // En Odoo 19 un many2one llega como {id, display_name}; en versiones previas
        // llegaba como [id, nombre]. Se contemplan las dos porque una regresión acá no
        // rompe nada visible: simplemente deja de aparecer el nombre, y eso pasa
        // desapercibido hasta que alguien lo busca.
        const valor = this.props.record.data.backend_id;
        if (!valor) {
            return "";
        }
        return Array.isArray(valor) ? valor[1] : valor.display_name || "";
    }

    get corriendo() {
        return this.state.estado === "running";
    }

    get termino() {
        return ["done", "partial"].includes(this.state.estado);
    }

    get porcentaje() {
        const total = this.state.total || 0;
        if (!total) {
            return 0;
        }
        return Math.round(((this.state.hechos + this.state.errores) / total) * 100);
    }

    get hayErrores() {
        return this.state.errores > 0;
    }

    get sinNovedades() {
        return this.corriendo && this.state.silencio >= SILENCIO_SOSPECHOSO;
    }

    get tiempo() {
        const s = this.state.segundos;
        return s < 60 ? _t("%s s", s) : _t("%s min %s s", Math.floor(s / 60), s % 60);
    }

    verHallazgos() {
        // Acción armada acá y no declarada en XML: la pantalla propia de hallazgos es A2.
        // Con vistas por defecto ya se pueden ver y filtrar; cuando A2 exista, esta misma
        // acción va a abrir las vistas buenas sin tocar el componente.
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Hallazgos de la auditoría"),
            res_model: "repo.audit.finding",
            views: [[false, "list"], [false, "form"]],
            domain: [["run_id", "=", this.corridaId]],
        });
    }
}

export const liveProgressField = {
    component: LiveProgress,
    supportedTypes: ["float", "integer"],
};

registry.category("fields").add("repo_live_progress", liveProgressField);
