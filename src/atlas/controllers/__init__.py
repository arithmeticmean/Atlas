"""HTTP controllers: one router per resource.

A controller parses the request, calls one service and shapes the response.
No rules and no storage: services raise domain errors, and
``controllers/errors.py`` is the one place that maps them to HTTP.
"""
