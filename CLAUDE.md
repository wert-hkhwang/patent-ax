# CLAUDE.md - Patent-AX AI Assistant Guide

This document provides comprehensive guidance for AI assistants working with the Patent-AX codebase.

## Project Overview

Patent-AX is a **patent-focused AI search system** built with LangGraph, Graph RAG, and vector search. It provides intelligent question-answering capabilities specifically for patent data, supporting semantic search, graph-based discovery, and SQL analysis.

### Key Capabilities
- **Vector Search (Qdrant)**: Semantic similarity-based patent search
- **Graph RAG (cuGraph)**: Graph traversal for related patents/applicants
- **SQL Analysis (PostgreSQL)**: Structured patent data statistics
- **Literacy Levels**: User-level customized responses (elementary/general/expert)

### Data Sources
- **Patents**: ~1.2M records in `f_patents` table
- **Applicants**: ~600K records in `f_patent_applicants` table
- **Vector Collection**: `patents_v3_collection` (1.82M points, 1024-dim)
- **Graph Nodes**: patent, applicant, ipc, org

## Tech Stack

| Component | Technology | Port |
|-----------|------------|------|
| LLM | EXAONE-4.0.1-32B (vLLM) | 12288 |
| Vector DB | Qdrant v1.7.4 | 6333 |
| Embedding | KURE API (1024-dim) | 7000 |
| Graph | cuGraph (GPU) | 8000 |
| RDBMS | PostgreSQL 15 | 5432 |
| Workflow | LangGraph | - |
| Backend | FastAPI | 8000 |
| Frontend | Next.js 14 | 3000 |

## Directory Structure

```
patent-ax/
├── api/                    # FastAPI backend
│   ├── main.py            # Main app entry, all routes
│   ├── config.py          # Qdrant collection settings
│   ├── streaming.py       # SSE streaming responses
│   ├── models.py          # Pydantic models
│   └── routers/           # API route modules
│       ├── ax_api.py      # Public AX API endpoints
│       └── user.py        # User profile management
│
├── workflow/              # LangGraph workflow engine
│   ├── graph.py           # Main workflow graph definition
│   ├── state.py           # AgentState definition
│   ├── edges.py           # Routing logic between nodes
│   ├── errors.py          # Custom exceptions
│   ├── search_config.py   # Search strategy configuration
│   ├── nodes/             # Workflow nodes
│   │   ├── analyzer.py         # Query analysis (LLM-based)
│   │   ├── sql_executor.py     # Natural language to SQL
│   │   ├── rag_retriever.py    # RAG search (vector + graph)
│   │   ├── generator.py        # Response generation
│   │   ├── merger.py           # Result merging (RRF)
│   │   ├── vector_enhancer.py  # Keyword expansion
│   │   ├── es_scout.py         # Elasticsearch scout
│   │   └── reasoning_analyzer.py
│   ├── loaders/           # Patent-specific data loaders
│   │   ├── patent_ranking_loader.py
│   │   ├── base_loader.py
│   │   └── registry.py
│   ├── prompts/           # Prompt templates
│   │   ├── reasoning_prompts.py
│   │   ├── filter_extraction.py
│   │   └── schema_context.py
│   └── user/              # User profile management
│
├── frontend/              # Next.js frontend
│   ├── app/               # Next.js App Router pages
│   │   ├── page.tsx       # Main page
│   │   ├── easy/          # Easy mode (elementary level)
│   │   ├── visualization/ # Data visualization
│   │   └── api/           # API routes (SSE proxy)
│   ├── components/        # React components
│   │   ├── easy/          # EasyChat component
│   │   ├── patent/        # PerspectiveTable
│   │   ├── user/          # User profile components
│   │   └── visualization/ # Graph/Vector visualizations
│   └── types/             # TypeScript types
│
├── sql/                   # SQL query generation
│   ├── sql_agent.py       # LLM-based SQL agent
│   ├── sql_prompts.py     # SQL generation prompts
│   ├── schema_analyzer.py # DB schema analysis
│   └── db_connector.py    # Database connection
│
├── graph/                 # cuGraph wrapper
│   ├── graph_rag.py       # GraphRAG implementation
│   ├── graph_builder.py   # Knowledge graph builder
│   ├── cugraph_client.py  # cuGraph API client
│   └── node_resolver.py   # Node resolution
│
├── llm/                   # LLM client
│   └── llm_client.py      # vLLM/OpenAI client wrapper
│
├── embedding/             # Vector embedding
│   └── embed_patent.py    # Patent embedding scripts
│
├── agent/                 # RAG agent
│   ├── rag_agent.py       # Main RAG agent
│   └── prompts.py         # Agent prompts
│
├── ontology/              # RnD ontology
│   ├── rnd_ontology.owl   # OWL ontology file
│   └── rnd_ontology.py    # Python interface
│
├── tests/                 # Test suite
│   ├── conftest.py        # Pytest fixtures
│   ├── test_patent_search.py
│   ├── test_service_health.py
│   └── ...
│
├── docs/                  # Documentation
│   ├── workflow_architecture.md
│   ├── TECHNICAL_WHITEPAPER.md
│   └── inspection/
│
├── .env.example           # Environment variables template
├── pytest.ini             # Pytest configuration
├── quick_start.sh         # Setup verification script
└── run_tests.sh           # Test runner script
```

## Development Setup

### 1. Environment Configuration

```bash
cp .env.example .env
# Edit .env with actual credentials (DB password, API keys)
```

### 2. Install Dependencies

```bash
# Python backend
pip install -r requirements.txt

# Frontend
cd frontend && npm install
```

### 3. Run Services

```bash
# Backend API
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend (in separate terminal)
cd frontend && npm run dev
```

### 4. Verify Setup

```bash
./quick_start.sh  # Checks all service connections
```

## Key Workflows

### LangGraph Workflow Pipeline

```
User Query
    ↓
[Analyzer] → Query analysis, entity_types=["patent"]
    ↓
[SQL Executor] → PostgreSQL query execution
    ↓
[RAG Retriever] → Qdrant vector + cuGraph traversal
    ↓
[Generator] → EXAONE-based response generation
    ↓
Final Response
```

### Query Types

| Type | Description | Route |
|------|-------------|-------|
| `sql` | Database queries (lists, aggregations) | SQL Executor |
| `rag` | Semantic/concept searches | RAG Retriever |
| `hybrid` | Combined SQL + RAG | Parallel execution |
| `simple` | Direct responses (greetings) | Generator only |

### Literacy Levels

| Level | Target Audience | Style |
|-------|-----------------|-------|
| L1 | Elementary students | Simple terms, emojis |
| L2 | General public | Clear explanations |
| L3 | SME practitioners | Technical details |
| L4 | Researchers | Academic depth |
| L5 | Patent attorneys | Legal precision |
| L6 | Policy makers | Strategic overview |

## Testing

### Run All Tests

```bash
./run_tests.sh
```

### Run Specific Tests

```bash
# Unit tests
pytest tests/test_nodes_unit.py -v

# Integration tests
pytest tests/ -m integration -v

# Patent search tests
pytest tests/test_patent_search.py -v

# Service health checks
pytest tests/test_service_health.py -v
```

### Frontend Build Verification

```bash
cd frontend && npm run build
```

## Key API Endpoints

### Main Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/workflow/chat/stream` | POST | SSE streaming chat |
| `/search` | POST | Single collection search |
| `/graph/search` | POST | Graph RAG search |
| `/sql/query` | POST | Natural language SQL |
| `/health` | GET | Health check |

### SSE Event Types

| Event | Description |
|-------|-------------|
| `text` | Response text chunk |
| `perspective_summary` | Perspective summary JSON |
| `status` | Processing status update |
| `done` | Streaming complete |
| `error` | Error occurred |

## Environment Variables

### Required Variables

```bash
# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ax
DB_USER=postgres
DB_PASSWORD=<password>

# External Services (GPU Server)
VLLM_BASE_URL=http://210.109.80.106:12288
QDRANT_URL=http://210.109.80.106:6333
KURE_API_URL=http://210.109.80.106:7000/api/embedding
CUGRAPH_API_URL=http://210.109.80.106:8000

# Workflow Settings
GRAPH_RAG_STRATEGY=hybrid  # vector_only | graph_only | hybrid
DEFAULT_LEVEL=일반인       # Literacy level
```

### Optional Variables

```bash
ES_MODE=off               # Elasticsearch mode
ES_SCOUT_ENABLED=false    # ES Scout feature
DEBUG=false               # Debug mode
```

## Code Conventions

### Python

- Use Python 3.9+ features
- Follow PEP 8 style guidelines
- Use type hints for function signatures
- Use docstrings for public functions
- Async/await for I/O operations in FastAPI

### TypeScript/React

- Use TypeScript strict mode
- Functional components with hooks
- Tailwind CSS for styling
- Next.js App Router conventions

### File Naming

- Python: `snake_case.py`
- TypeScript: `PascalCase.tsx` for components, `camelCase.ts` for utilities
- Tests: `test_<module>.py`

### Commit Messages

Use conventional commits:
- `feat:` New features
- `fix:` Bug fixes
- `docs:` Documentation
- `refactor:` Code refactoring
- `test:` Test additions/changes

## Important Design Decisions

### 1. Patent-Only Domain

The system is hardcoded for patent domain only:
- `entity_types=["patent"]` is enforced in `workflow/state.py:258`
- `analyzer.py:998` always returns `entity_types: ["patent"]`
- Only `patents_v3_collection` is used in Qdrant

### 2. Streaming Architecture

SSE (Server-Sent Events) is used for real-time responses:
- Backend: `api/streaming.py` handles SSE generation
- Frontend: `app/api/workflow/chat/stream/route.ts` proxies SSE

### 3. Perspective Summaries

Patent documents are summarized from 4 perspectives:
- `purpose`: Objective (from objectko field)
- `material`: Materials (from solutionko)
- `method`: Methods (from solutionko)
- `effect`: Effects (from abstract)

## Common Tasks

### Adding a New API Endpoint

1. Add Pydantic models in `api/models.py`
2. Add route handler in `api/main.py` or create a new router
3. Add tests in `tests/test_api_*.py`

### Modifying Workflow Logic

1. Update node logic in `workflow/nodes/<node>.py`
2. Update routing in `workflow/edges.py` if needed
3. Update state in `workflow/state.py` if new fields needed
4. Add tests in `tests/test_workflow.py`

### Adding Frontend Components

1. Create component in `frontend/components/`
2. Add types in `frontend/types/` if needed
3. Import and use in relevant page

### Database Schema Changes

1. Add migration in `sql/migrations/`
2. Update `sql/schema_analyzer.py`
3. Update relevant loaders in `workflow/loaders/`

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| `entity_types` errors | Check `analyzer.py:998` hardcoding |
| Collection not found | Verify Qdrant connection and collection name |
| Loader errors | Check `workflow/loaders/__init__.py` |
| SQL generation fails | Check `sql/sql_prompts.py` schema context |

### Service Health Checks

```bash
# Qdrant
curl http://210.109.80.106:6333/collections/patents_v3_collection

# vLLM
curl http://210.109.80.106:12288/health

# KURE Embedding
curl http://210.109.80.106:7000/health

# PostgreSQL
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT COUNT(*) FROM f_patents;"
```

## Key Files Reference

| File | Purpose | Line Numbers to Note |
|------|---------|---------------------|
| `workflow/state.py` | AgentState definition | L258: entity_types hardcoding |
| `workflow/nodes/analyzer.py` | Query analysis | L998: entity_types return |
| `workflow/graph.py` | Main workflow graph | Entry point for workflow |
| `api/main.py` | API entry point | All route definitions |
| `api/streaming.py` | SSE implementation | SSE event generation |
| `workflow/nodes/generator.py` | Response generation | Literacy level handling |

## Documentation

- [Workflow Architecture](docs/workflow_architecture.md) - Detailed workflow documentation
- [Technical Whitepaper](docs/TECHNICAL_WHITEPAPER.md) - System design document
- [API Endpoints](docs/APPENDIX_A_API_ENDPOINTS.md) - Full API reference
- [Database Schema](docs/APPENDIX_B_DATABASE_SCHEMA.md) - Database structure
- [User Literacy Guide](docs/USER_LITERACY_GUIDE.md) - Literacy level details

---

*Last Updated: 2026-01-22*
*Version: Patent-AX v1.0.0*
