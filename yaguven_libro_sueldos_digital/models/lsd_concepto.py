# -*- coding: utf-8 -*-
"""Grilla de bases de cada concepto, tal como esta registrada en ARCA.

Las nueve bases imponibles del registro 04 NO se declaran libremente: ARCA las
determina sumando los conceptos del registro 03, y a cada concepto le aplica la
grilla que el contribuyente tiene registrada en el portal LSD (seccion
"Conceptos"). Si lo que informamos no coincide con esa suma, rechaza el archivo.

Hasta la version 6.2 el wizard adivinaba la composicion con reglas escritas a
mano ("el no remunerativo va a las bases 4 y 8"), y eso fallo tres veces
seguidas sobre el libro de agosto 2026, siempre por el mismo motivo: la
composicion no depende de si el concepto es remunerativo, depende del concepto.
Medido contra el catalogo bajado del portal:

    572 NO REM EXTRAORDINARIO (UOM/ASIMRA) -> obra social y FSR, NO LRT
    573 NR RETROACTIVO        (UOM/ASIMRA) -> obra social y FSR, NO LRT
    535 COMP. POR REFRIGERIO  (SOEVA)      -> SOLO LRT
    556 ASIG NO REM AC 2021   (SOEVA)      -> SOLO LRT

Con esta tabla el wizard arma las bases igual que ARCA, sumando concepto por
concepto. La fuente es el propio portal: ARCA / Libro de Sueldos Digital /
Conceptos / "Conceptos del contribuyente", que se baja como TXT separado por
";". El importador de abajo lee ese archivo tal cual viene.
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Columna del TXT del portal -> campo del modelo. El TXT trae 20 columnas; las
# que no entran acá (RENATEA, marca repetible) no alimentan ninguna base del
# registro 04.
COLUMNAS = {
    5: 'aporte_sipa',        # Aportes SIPA
    6: 'contrib_sipa',       # Contribuciones SIPA
    7: 'aporte_inssjp',      # Aportes INSSJyP
    8: 'contrib_inssjp',     # Contribuciones INSSJyP
    9: 'aporte_os',          # Aportes obra social
    10: 'contrib_os',        # Contribuciones obra social
    11: 'aporte_fsr',        # Aportes FSR
    12: 'contrib_fsr',       # Contribuciones FSR
    15: 'contrib_aaff',      # Contribuciones AAFF
    16: 'contrib_fne',       # Contribuciones FNE
    17: 'contrib_lrt',       # Contribuciones LRT
    18: 'aporte_diferencial',
    19: 'aporte_especial',
}


class LsdConcepto(models.Model):
    _name = 'lsd.concepto'
    _description = 'Concepto del LSD y bases que integra'
    _order = 'codigo'
    _rec_name = 'codigo'

    codigo = fields.Char(
        'Código propio', required=True, index=True,
        help='El código del empleador, el mismo que viaja en el registro 03 '
             'y que se imprime en el recibo.')
    name = fields.Char('Descripción')
    codigo_afip = fields.Char('Concepto ARCA')
    name_afip = fields.Char('Descripción ARCA')
    company_id = fields.Many2one(
        'res.company', 'Compañía', required=True, index=True,
        default=lambda s: s.env.company)

    aporte_sipa = fields.Boolean('Aportes SIPA')
    contrib_sipa = fields.Boolean('Contribuciones SIPA')
    aporte_inssjp = fields.Boolean('Aportes INSSJyP')
    contrib_inssjp = fields.Boolean('Contribuciones INSSJyP')
    aporte_os = fields.Boolean('Aportes obra social')
    contrib_os = fields.Boolean('Contribuciones obra social')
    aporte_fsr = fields.Boolean('Aportes FSR')
    contrib_fsr = fields.Boolean('Contribuciones FSR')
    contrib_aaff = fields.Boolean('Contribuciones AAFF')
    contrib_fne = fields.Boolean('Contribuciones FNE')
    contrib_lrt = fields.Boolean('Contribuciones LRT')
    aporte_diferencial = fields.Boolean('Aportes diferenciales')
    aporte_especial = fields.Boolean('Aportes especiales')

    _sql_constraints = [
        ('codigo_company_uniq', 'unique(codigo, company_id)',
         'Ya hay un concepto con ese código en esta compañía.'),
    ]

    # Base imponible del reg 04 -> campo que la alimenta. El orden es el de
    # BI1..BI9 tal como se escriben en las posiciones 176-310.
    BASES = ('aporte_sipa', 'contrib_sipa', 'aporte_inssjp', 'aporte_os',
             'contrib_inssjp', 'aporte_diferencial', 'aporte_especial',
             'contrib_os', 'contrib_lrt')

    @api.model
    def grilla(self, company):
        """Devuelve {codigo: (b1..b9)} con 1/0 por base, para esa compañía."""
        out = {}
        for c in self.search([('company_id', '=', company.id)]):
            out[c.codigo] = tuple(1 if c[f] else 0 for f in self.BASES)
        return out

    @api.model
    def importar_txt(self, contenido, company=None):
        """Carga/actualiza la tabla desde el TXT del portal LSD.

        `contenido` es el archivo tal cual se baja de ARCA / Libro de Sueldos
        Digital / Conceptos / "Conceptos del contribuyente": una cabecera y una
        fila por concepto, separadas por ';'.
        """
        company = company or self.env.company
        if isinstance(contenido, bytes):
            contenido = contenido.decode('latin-1')
        filas = [f for f in contenido.splitlines() if f.strip()]
        if not filas:
            raise UserError(_('El archivo de conceptos está vacío.'))
        creados = actualizados = 0
        existentes = {c.codigo: c for c in self.search(
            [('company_id', '=', company.id)])}
        for fila in filas[1:]:                       # la primera es la cabecera
            partes = fila.split(';')
            if len(partes) < 20:
                continue
            codigo = partes[2].strip()
            if not codigo:
                continue
            vals = {
                'name': partes[3].strip(),
                'codigo_afip': partes[0].strip(),
                'name_afip': partes[1].strip(),
                'company_id': company.id,
            }
            vals.update({campo: partes[i].strip() == '1'
                         for i, campo in COLUMNAS.items()})
            rec = existentes.get(codigo)
            if rec:
                rec.write(vals)
                actualizados += 1
            else:
                self.create(dict(vals, codigo=codigo))
                creados += 1
        return {'creados': creados, 'actualizados': actualizados}
