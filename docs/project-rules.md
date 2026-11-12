# AlphaDesk Project Rules

These add to `CodingStandards.md`. They are specific to this project.

## Stack

- FastAPI for the API. LangGraph and LangChain for agents. Pydantic for all data contracts.
- Azure OpenAI for models. LangSmith for tracing. DeepEval for evals.
- Postgres, Qdrant and Redis run through Docker Compose.
- Check the current LangChain and LangGraph docs before using an API. These libraries change often. Do not rely on older patterns from memory.

## Where code goes

| Folder | Holds | Must not hold |
|---|---|---|
| `api/` | Routes, request and response models | Business logic |
| `graph/` | Graph, state, routing | HTTP calls, SQL |
| `agents/` | One module per agent: its prompt, tools and output type | Shared business logic |
| `prompts/` | Prompt text files | Code |
| `tools/` | Thin tool wrappers the LLM can call | Real logic. That lives in `services/`. |
| `services/` | Business logic and calculations | LangChain or FastAPI imports |
| `integrations/` | Clients for outside APIs (Finnhub, SEC EDGAR) | Business rules |
| `domain/` | Pydantic models shared across the app | Framework imports |
| `config/` | Settings | Secrets in code |

## AI rules

- **Prompts live in files** under `prompts/`, never as inline strings.
- **All model access goes through the model factory.** No direct model construction elsewhere.
- **Every agent output is a Pydantic model.** Agents never pass free text to each other.
- **Numbers come from tools and code, never from the model.** Any calculation is a plain function in `services/`.
- **Every tool result carries its source URL and an as-of time.**
- **Tools return errors as data.** A failed tool returns a typed error result the model can read. It does not raise into the agent loop.
- **Retrieved text is data, not instructions.** Never let text from a tool change the agent's rules.
- **No LLM may call a tool that changes state.**
- **Log token counts and cost** for every model call.

## Testing rules

- Unit tests never call a real LLM or a real outside API. Use a fake chat model and fake clients.
- Evals call a real LLM. Mark them with the `eval` pytest marker. They run with `make eval`, not `make check`.
- Every tool has a unit test for success, for a bad input, and for an upstream failure.

## Secrets and config

- All keys come from environment variables through `config/`. Keep `.env.example` up to date.
- SEC EDGAR requires a User-Agent header that identifies the caller with a contact email. Read it from settings.
