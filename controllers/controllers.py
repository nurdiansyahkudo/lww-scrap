# -*- coding: utf-8 -*-
# from odoo import http


# class LwwScrap(http.Controller):
#     @http.route('/lww_scrap/lww_scrap', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/lww_scrap/lww_scrap/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('lww_scrap.listing', {
#             'root': '/lww_scrap/lww_scrap',
#             'objects': http.request.env['lww_scrap.lww_scrap'].search([]),
#         })

#     @http.route('/lww_scrap/lww_scrap/objects/<model("lww_scrap.lww_scrap"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('lww_scrap.object', {
#             'object': obj
#         })

