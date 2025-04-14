from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_is_zero, float_compare
import logging

_logger = logging.getLogger(__name__)

class StockScrap(models.Model):
    _inherit = 'stock.scrap'

    lot_ids = fields.Many2many(
        'stock.lot', string='Lots/Serials',
        domain="[('product_id', '=', product_id), ('product_qty', '>', 0)]",
        check_company=True
    )

    def _get_total_lot_quantity(self):
        """Hitung total kuantitas berdasarkan lot_ids."""
        total_qty = 0.0
        for lot in self.lot_ids:
            # Cari stock.quant untuk lot tertentu di lokasi tertentu
            quant = self.env['stock.quant'].search([
                ('lot_id', '=', lot.id),
                ('location_id', '=', self.location_id.id),
                ('quantity', '>', 0)
            ], limit=1)
            if quant:
                total_qty += quant.quantity
                _logger.info(f"Lot {lot.name}: Quantity = {quant.quantity}")
            else:
                _logger.warning(f"No quant found for Lot {lot.name} in Location {self.location_id.name}")
        
        _logger.info(f"Total Quantity for Scrap ID {self.id}: {total_qty}")
        return total_qty

    def _sync_scrap_qty(self):
        """Sinkronisasi scrap_qty berdasarkan lot_ids."""
        for scrap in self:
            if scrap.lot_ids:
                # Gunakan metode baru untuk menghitung total kuantitas
                scrap.scrap_qty = scrap._get_total_lot_quantity()
            elif not scrap.scrap_qty:
                scrap.scrap_qty = 1.0  # Default jika tidak ada lot

    @api.model_create_multi
    def create(self, vals_list):
        """Sinkronisasi scrap_qty saat record dibuat."""
        records = super().create(vals_list)
        records._sync_scrap_qty()
        return records

    def write(self, vals):
        """Sinkronisasi scrap_qty saat record diubah."""
        res = super().write(vals)
        if 'lot_ids' in vals:
            self._sync_scrap_qty()
        return res

    @api.onchange('lot_ids')
    def _onchange_lot_ids_set_scrap_qty(self):
        """Perbarui scrap_qty saat lot_ids berubah."""
        if self.lot_ids:
            self.scrap_qty = self._get_total_lot_quantity()

    def action_validate(self):
        """Validasi sebelum melakukan proses scrap."""
        self.ensure_one()

        # Sinkronisasi ulang scrap_qty sebelum validasi
        if self.lot_ids:
            self.scrap_qty = self._get_total_lot_quantity()
            _logger.info(f"Scrap Quantity after calculation: {self.scrap_qty}")

        # Pastikan nilai scrap_qty positif
        if float_is_zero(self.scrap_qty, precision_rounding=self.product_uom_id.rounding):
            raise UserError(_('You can only enter positive quantities.'))

        # Periksa ketersediaan kuantitas sebelum scrap
        if self.check_available_qty():
            return self.do_scrap()

        # Jika kuantitas tidak mencukupi, tampilkan peringatan
        ctx = dict(self.env.context)
        ctx.update({
            'default_product_id': self.product_id.id,
            'default_location_id': self.location_id.id,
            'default_scrap_id': self.id,
            'default_quantity': self.product_uom_id._compute_quantity(self.scrap_qty, self.product_id.uom_id),
            'default_product_uom_name': self.product_id.uom_name
        })
        
        _logger.warning(f"Insufficient quantity to scrap for Scrap ID {self.id}. Available: {self.check_available_qty()}")
        
        return {
            'name': _('%(product)s: Insufficient Quantity To Scrap', product=self.product_id.display_name),
            'view_mode': 'form',
            'res_model': 'stock.warn.insufficient.qty.scrap',
            'view_id': self.env.ref('stock.stock_warn_insufficient_qty_scrap_form_view').id,
            'type': 'ir.actions.act_window',
            'context': ctx,
            'target': 'new'
        }

    def check_available_qty(self):
        """Periksa ketersediaan kuantitas untuk scrapping."""
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

        _logger.info(f"Available Quantity: {available_qty}, Scrap Quantity: {scrap_qty} for Scrap ID {self.id}")

        return float_compare(available_qty, scrap_qty, precision_digits=precision) >= 0

    def do_scrap(self):
        """Proses scrapping produk."""
        self._check_company()
        for scrap in self:
            # Sinkronisasi ulang scrap_qty sebelum melakukan proses scrap
            if scrap.lot_ids:
                calculated_qty = scrap._get_total_lot_quantity()
                scrap.write({'scrap_qty': calculated_qty})

            # Buat gerakan stok untuk setiap lot atau produk secara keseluruhan
            scrap.name = self.env['ir.sequence'].next_by_code('stock.scrap') or _('New')
            moves = []
            if scrap.lot_ids:
                for lot in scrap.lot_ids:
                    move = self.env['stock.move'].create(scrap._prepare_move_values_per_lot(lot))
                    moves.append(move)
            else:
                move = self.env['stock.move'].create(scrap._prepare_move_values())
                moves.append(move)

            # Selesaikan gerakan stok
            for move in moves:
                move.with_context(is_scrap=True)._action_done()

            # Perbarui status dan tanggal selesai
            scrap.write({'state': 'done', 'date_done': fields.Datetime.now()})
            
            # Jika perlu replenishment, lakukan replenishment
            if scrap.should_replenish:
                scrap.do_replenish()
        
        return True
