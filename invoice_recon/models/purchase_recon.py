# -*- coding: utf-8 -*-

import base64
import csv
from cStringIO import StringIO
from odoo import models, fields, api, _
import odoo.addons.decimal_precision as dp
from odoo.exceptions import UserError


class PurchaseRecon(models.Model):
    _name = 'purchase.recon'
    _order = 'id desc'

    name = fields.Char('Reference', required=True, copy=False, default='New', readonly=1)
    vendor_reference = fields.Char('Vendor Reference')
    notes = fields.Text('Notes')
    recon_line_ids = fields.One2many('purchase.recon.line', 'recon_id', string='Invoice Lines')
    import_file = fields.Binary('Import File')
    import_filename = fields.Char('Import File Name', compute='_compute_import_file_name')
    partner_id = fields.Many2one('res.partner', 'Vendor', required=True, domain=[('dropshipper_code', '!=', False)])
    recon_lines_count = fields.Integer('# of Invoice Lines', compute='_compute_recon_lines_count')
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], 'Status', default='draft')
    total_variance = fields.Float(compute='_compute_total_variance', string='Total Variance', readonly=True, store=True, digits=dp.get_precision('Product Price'))
    total_amt = fields.Float(compute='_compute_total_amt', string='Total Amt', readonly=True, store=True, digits=dp.get_precision('Product Price'))

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('purchase.recon') or 'New'
        return super(PurchaseRecon, self).create(vals)

    @api.multi
    @api.depends('recon_line_ids.variance')
    def _compute_total_variance(self):
        for r in self:
            r.total_variance = sum(l.variance for l in r.recon_line_ids)

    @api.multi
    @api.depends('recon_line_ids.total_price')
    def _compute_total_amt(self):
        for r in self:
            r.total_amt = sum(l.total_price for l in r.recon_line_ids)

    @api.multi
    @api.depends('recon_line_ids')
    def _compute_recon_lines_count(self):
        for r in self:
            r.recon_lines_count = len(r.recon_line_ids)

    @api.multi
    @api.depends('name')
    def _compute_import_file_name(self):
        for r in self:
            r.import_filename = (r.name or 'New') + '.csv'

    @api.multi
    def action_view_recon_lines(self):
        action = self.env.ref('invoice_recon.action_purchase_recon_line')
        result = action.read()[0]
        result['context'] = {}
        recon_line_ids = sum([r.recon_line_ids.ids for r in self], [])
        result['domain'] = "[('id','in',[" + ','.join(map(str, recon_line_ids)) + "])]"
        return result

    @api.multi
    def button_import_lines_from_file(self):
        self.ensure_one()
        if not self.import_file:
            raise UserError(_('There is nothing to import.'))
        data = csv.reader(StringIO(base64.b64decode(self.import_file)), quotechar='"', delimiter=',')
        # Read the column names from the first line of the file
        import_fields = data.next()

        required_cols = ['PO Reference', 'Vendor PO Reference', 'Product Price']
        if any(col not in import_fields for col in required_cols):
            raise UserError(_('File should be a comma-separated file with columns named PO Reference, Vendor PO Reference, and Product Price. Optional columns are Shipping Price and Handling Price.'))
        rows = []
        for row in data:
            items = dict(zip(import_fields, row))
            rows.append(items)

        if not rows:
            return

        counter = 1
        for row in rows:
            try:
                values = {
                    'name': row['PO Reference'].strip(),
                    'recon_id': self.id,
                    'vendor_ref': row['Vendor PO Reference'],
                    'product_price': float(row['Product Price']),
                    'shipping_price': float(row['Shipping Price']) if 'Shipping Price' in row else 0.0,
                    'handling_price': float(row['Handling Price']) if 'Handling Price' in row else 0.0,
                    'partner_id': self.partner_id.id
                }
                self.env['purchase.recon.line'].create(values)
                counter += 1
            except:
                raise UserError(_('Row %s has invalid data.') %(counter,))

    @api.multi
    def button_reconcile(self):
        self.ensure_one()
        for line in self.recon_line_ids:
            state = 'draft'
            variance = 0.0
            po_id = self.env['purchase.order'].search([('name', '=', line.name), ('state', 'in', ('purchase', 'done'))], limit=1)
            if po_id:
                if po_id.recon_line_ids:
                    state = 'duplicate'
                    # line.write({'state': 'duplicate', 'purchase_order_id': po_id.id })
                else:
                    state = 'matched'
                    # line.write({'state': 'matched', 'purchase_order_id': po_id.id})
            else:
                state = 'notfound'

            if state in ['notfound', 'duplicate']:
                variance = -line.total_price
            elif state == 'matched':
                variance = po_id.amount_total - line.total_price
            else:
                variance = 0.0
            line.write({'state': state, 'purchase_order_id': po_id.id, 'variance': variance })
        self.write({'state': 'done'})

    @api.multi
    def button_undo_recon(self):
        self.ensure_one()
        for line in self.recon_line_ids:
            line.write({'state': 'draft', 'purchase_order_id': False})
        self.write({'state': 'draft'})

    @api.multi
    def button_unlink_recon_lines(self):
        self.ensure_one()
        self.recon_line_ids.unlink()

    @api.multi
    def button_download_summary(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/reports/recon?id=%s' % (self.id),
            'target': 'new',
        }


class PurchaseReconLine(models.Model):
    _name = 'purchase.recon.line'
    _order = 'name'

    name = fields.Char('PO Reference', required=True)
    vendor_ref = fields.Char('Vendor PO Reference')
    recon_id = fields.Many2one('purchase.recon', 'Recon Reference', required=True)
    shipping_price = fields.Float('Shipping Price', digits=dp.get_precision('Product Price'))
    handling_price = fields.Float('Handling Price', digits=dp.get_precision('Product Price'))
    product_price = fields.Float('Item Price', digits=dp.get_precision('Product Price'))
    total_price = fields.Float(compute='_compute_amount', string='Total', readonly=True, store=True, digits=dp.get_precision('Product Price'))
    purchase_order_id = fields.Many2one('purchase.order', 'PO Match')
    variance = fields.Float(string='Variance')
    state = fields.Selection([('draft', 'Draft'), ('matched', 'Matched'), ('duplicate', 'Duplicate'), ('notfound', 'Not Found')], 'Status', default='draft', copy=False)
    partner_id = fields.Many2one(related='recon_id.partner_id', string='Vendor')
    note = fields.Char('Note')

    @api.multi
    @api.depends('shipping_price', 'handling_price', 'product_price')
    def _compute_amount(self):
        for line in self:
            line.total_price = line.shipping_price + line.handling_price + line.product_price
