__all__ = ["ParsingError", "UnreadableFile", "UnsupportedFile"]


class ParsingError(Exception):
    """A file could not be turned into chunks."""


class UnsupportedFile(ParsingError):
    """Not a type Atlas reads, whatever its name says."""


class UnreadableFile(ParsingError):
    """The type is supported, but this file could not be read (corrupt,
    encrypted, or no extractable text, like a scanned PDF)."""
