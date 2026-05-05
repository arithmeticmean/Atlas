# AGENTS.md

Guide for AI agents working in the Atlas codebase.

## Project Overview

Atlas is a document processing and ingestion pipeline with vector storage capabilities. It parses documents (Markdown, potentially others), splits them into chunks, and stores them in PostgreSQL with pgvector for semantic search.

## Technology Stack

- **Python**: 3.11+
- **Package Manager**: `uv` (not pip)
- **Database**: PostgreSQL with asyncpg, SQLAlchemy 2.0 (async), Alembic migrations
- **Vector Storage**: pgvector
- **Configuration**: Pydantic-settings with `.env` file

## Essential Commands

```bash
# Install dependencies
uv sync

# Run the application
uv run python main.py

# Database migrations
uv run alembic upgrade head          # Apply all migrations
uv run alembic downgrade -1          # Rollback one migration
uv run alembic revision --autogenerate -m "description"  # Create new migration

# Run tests (when implemented)
uv run pytest
```

## Project Structure

```
├── config/              # Pydantic-settings configuration
│   ├── __init__.py      # Exports settings singleton
│   └── config.py        # Settings class with DATABASE_URL
├── db/                  # Database layer
│   ├── database.py      # Async SQLAlchemy engine, Base class
│   └── models/          # ORM models
│       ├── documents.py # Document, DocumentSection, DocumentChunk
│       └── workspace.py # Workspace, WorkspaceMode
├── document/            # Document domain models
│   └── model.py         # RawDocument dataclass
├── parser/              # Document parsing framework
│   ├── parser.py        # DocumentParser ABC, ElementType enum
│   └── markdown.py      # MarkDownParser implementation
├── ingest/              # Document ingestion (WIP)
│   └── ingest.py
├── migrations/          # Alembic migrations
│   └── versions/
├── service/             # Service layer (empty, for future use)
└── tests/               # Tests (empty)
```

## Key Patterns & Conventions

### Database Models

Use SQLAlchemy 2.0 style with `Mapped` and `mapped_column`:

```python
from sqlalchemy.orm import Mapped, mapped_column
from db.database import Base

class MyModel(Base):
    __tablename__ = "my_models"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
```

**Always use async SQLAlchemy** - the engine is created with `create_async_engine()`. Never use sync SQLAlchemy operations.

### Configuration

Access settings via the cached singleton:

```python
from config import settings

database_url = settings.database_url  # Loaded from .env file
```

Required environment variables (in `.env`):
- `DATABASE_URL` - PostgreSQL connection string with asyncpg driver (e.g., `postgresql+asyncpg://user:pass@localhost/dbname`)

### Document Parser Framework

Parsers implement the `DocumentParser` ABC:

```python
from parser import DocumentParser, DocumentElement, ElementType
from document import RawDocument

class MyParser(DocumentParser):
    def parse(self, document: RawDocument) -> Iterable[DocumentElement]:
        # document.data is bytes
        # Yield DocumentElement instances
        yield DocumentElement(
            type=ElementType.PARAGRAPH,
            content="parsed text",
            level=None,  # For headings
            page=None,   # For PDFs
        )
```

### Type Hints

Use modern Python 3.11+ syntax:
- `str | None` instead of `Optional[str]`
- `list[str]` instead of `List[str]`

## Important Gotchas

1. **Broken/Incomplete Code Exists**:
   - `parser/markdown.py:26` - Incomplete match statement (syntax error)
   - `ingest/ingest.py` - Imports non-existent `SourceDocument`
   - `db/models/__init__.py` - Imports non-existent `User` model
   - Migration file is empty (no actual table creation)

2. **Module Imports**: 
   - Use absolute imports from project root (e.g., `from document import RawDocument`)
   - Some modules lack `__init__.py` files (`db/`, `ingest/`)

3. **Database IDs**:
   - Workspaces use `uuid.UUID` with auto-generated defaults
   - Documents, Sections, Chunks use `str` IDs (application-managed)

4. **Async Throughout**:
   - All database operations are async
   - Use `AsyncSessionLocal` for sessions
   - Migrations use async engine (`async_engine_from_config`)

5. **Vector Search Setup**:
   - pgvector extension required in PostgreSQL
   - `DocumentChunk` has `embedding_model` field but no embedding vector column yet

## Adding New Features

### New Parser

1. Create class inheriting from `DocumentParser`
2. Implement `parse()` method yielding `DocumentElement`
3. Add to `parser/__init__.py` exports
4. Register MIME type mapping (when ingest layer is ready)

### New Database Model

1. Define model in `db/models/` using SQLAlchemy 2.0 syntax
2. Import in `migrations/env.py` (line 30: `target_metadata = Base.metadata`)
3. Generate migration: `uv run alembic revision --autogenerate -m "add model"`
4. Review migration before applying - auto-generation may need adjustments

### New Configuration Option

1. Add field to `Settings` class in `config/config.py`
2. It will automatically load from environment variables
3. Update `.env` file with the new variable
