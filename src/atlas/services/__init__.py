"""Application services: what happens, and who may do it.

Each service carries out use cases -- sign in, upload a document, answer a
question -- through the repositories (``atlas.repository``), and will call
the AI layer where a model is needed (marked ``# AI:`` until it exists). They
know nothing about HTTP: errors are raised as ``services.errors`` and the
controllers turn them into responses.

No re-exports: import from the module that defines the name.
"""
