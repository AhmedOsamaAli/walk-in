"""The API's endpoints, by resource. Each module has its router; app.main includes them all.

meta       whether the server is up and what it can reach (GET /api/health), the preset sites (GET /api/presets)
surveys    running a survey and streaming it (GET /api/run), its record (GET /api/runs/{id}), design sheets
places     the map's lookups: catchment, heatmap, the owner's place on Qloo, addresses both ways
account    public settings, sign-in and sign-out, the signed-in user, My places and deleting the account
kits       launch kits (free): making one for a concept, its page and building it again
examples   the finished example surveys anyone can open (GET /api/examples), loaded into memory at startup
"""
