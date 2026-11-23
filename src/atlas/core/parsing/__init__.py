"""Turn an uploaded file into LangChain chunks, lazily.

Public API, in ``atlas.core.parsing.pipeline``:

``FileInput(content, filename=None, mime_type=None)``
    A file to read. ``content`` must be a seekable binary stream.

``FileChunker(chunk_size=, chunk_overlap=, batch_size=16)``
    A LangChain ``Runnable``. ``invoke`` returns every chunk; ``stream`` and
    ``astream`` yield lists of chunks lazily, for large files. Each chunk has
    ``page`` (0 if the format has no pages) and ``file_type`` metadata.

``ensure_supported(file)``
    Raise ``UnsupportedFile`` unless Atlas can read this file. Blocking.

``supported_file_types()``
    Supported extensions, grouped by ``FileKind``.

Errors are in ``atlas.core.parsing.errors``: ``UnsupportedFile`` for a type
Atlas does not read, ``UnreadableFile`` for a damaged or empty file.
"""
