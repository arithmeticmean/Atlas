"""The Atlas backend.

Deliberately empty of re-exports. Importing any module under ``service.``
executes this file first, so a convenience barrel here would put the entire
application service layer -- and through it langchain, SQLAlchemy and numpy --
on the import path of every leaf module. ``service.config.paths`` is read by
every CLI command, and it must stay cheap.

Import from the module that defines the name: ``from service.core.auth import
AuthService``, not ``from service import AuthService``.
"""
