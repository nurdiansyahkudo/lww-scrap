from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_is_zero, float_compare

class StockScrap(models.Model):
    _inherit = 'stock.scrap'

    lot_ids = fields.Many2many(
        'stock.lot', string='Lots/Serials',
        domain="[('product_id', '=', product_id), ('product_qty', '>', 0)]",
        check_company=True
    )

    @api.onchange('lot_ids')
    def _onchange_lot_ids_set_scrap_qty(self):
        if self.lot_ids:
            self.scrap_qty = sum(lot.product_qty for lot in self.lot_ids)
        else:
            self.scrap_qty = 1.0

    def _prepare_move_values(self):
        self.ensure_one()
        return {
            'name': self.name,
            'origin': self.origin or self.picking_id.name or self.name,
            'company_id': self.company_id.id,
            'product_id': self.product_id.id,
            'product_uom': self.product_uom_id.id,
            'state': 'draft',
            'product_uom_qty': self.scrap_qty,
            'location_id': self.location_id.id,
            'scrapped': True,
            'scrap_id': self.id,
            'location_dest_id': self.scrap_location_id.id,
            'move_line_ids': [(0, 0, {
                'product_id': self.product_id.id,
                'product_uom_id': self.product_uom_id.id,
                'quantity': self.scrap_qty,
                'location_id': self.location_id.id,
                'location_dest_id': self.scrap_location_id.id,
                'package_id': self.package_id.id,
                'owner_id': self.owner_id.id,
                'lot_id': self.lot_id.id,
            })],
            'picked': True,
            'picking_id': self.picking_id.id
        }

    def _prepare_move_values_per_lot(self, lot):
        self.ensure_one()
        return {
            'name': self.name,
            'origin': self.origin or self.picking_id.name or self.name,
            'company_id': self.company_id.id,
            'product_id': self.product_id.id,
            'product_uom': self.product_uom_id.id,
            'state': 'draft',
            'product_uom_qty': lot.product_qty,
            'location_id': self.location_id.id,
            'scrapped': True,
            'scrap_id': self.id,
            'location_dest_id': self.scrap_location_id.id,
            'move_line_ids': [(0, 0, {
                'product_id': self.product_id.id,
                'product_uom_id': self.product_uom_id.id,
                'quantity': lot.product_qty,
                'location_id': self.location_id.id,
                'location_dest_id': self.scrap_location_id.id,
                'package_id': self.package_id.id,
                'owner_id': self.owner_id.id,
                'lot_id': lot.id,
            })],
            'picked': True,
            'picking_id': self.picking_id.id
        }

    def do_scrap(self):
        self._check_company()
        for scrap in self:
            scrap.name = self.env['ir.sequence'].next_by_code('stock.scrap') or _('New')
            moves = []
            if scrap.lot_ids:
                for lot in scrap.lot_ids:
                    move = self.env['stock.move'].create(scrap._prepare_move_values_per_lot(lot))
                    moves.append(move)
                total_qty = sum(lot.product_qty for lot in scrap.lot_ids)
            else:
                move = self.env['stock.move'].create(scrap._prepare_move_values())
                moves.append(move)
                total_qty = scrap.scrap_qty  # default

            for move in moves:
                move.with_context(is_scrap=True)._action_done()

            scrap.write({
                'scrap_qty': total_qty,
                'state': 'done',
                'date_done': fields.Datetime.now()
            })

            if scrap.should_replenish:
                scrap.do_replenish()
        return True

    def check_available_qty(self):
        if not self._should_check_available_qty():
            return True
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        available_qty = sum(
            self.with_context(
                location=self.location_id.id,
                lot_id=lot.id,
                package_id=self.package_id.id,
                owner_id=self.owner_id.id,
                strict=True,
            ).product_id.qty_available
            for lot in self.lot_ids
        )
        scrap_qty = self.product_uom_id._compute_quantity(self.scrap_qty, self.product_id.uom_id)
        return float_compare(available_qty, scrap_qty, precision_digits=precision) >= 0

    def action_validate(self):
        self.ensure_one()
        if float_is_zero(self.scrap_qty, precision_rounding=self.product_uom_id.rounding):
            raise UserError(_('You can only enter positive quantities.'))
        if self.check_available_qty():
            return self.do_scrap()
        ctx = dict(self.env.context)
        ctx.update({
            'default_product_id': self.product_id.id,
            'default_location_id': self.location_id.id,
            'default_scrap_id': self.id,
            'default_quantity': self.product_uom_id._compute_quantity(self.scrap_qty, self.product_id.uom_id),
            'default_product_uom_name': self.product_id.uom_name
        })
        return {
            'name': _('%(product)s: Insufficient Quantity To Scrap', product=self.product_id.display_name),
            'view_mode': 'form',
            'res_model': 'stock.warn.insufficient.qty.scrap',
            'view_id': self.env.ref('stock.stock_warn_insufficient_qty_scrap_form_view').id,
            'type': 'ir.actions.act_window',
            'context': ctx,
            'target': 'new'
        }