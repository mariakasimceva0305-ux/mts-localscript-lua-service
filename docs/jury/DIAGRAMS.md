# Диаграммы (ASCII) для жюри

---

## 1. Architecture

```
                    ┌──────────────────────────────────────┐
                    │           Host (Docker)               │
                    │                                      │
   User / script     │   ┌─────────┐      ┌──────────────┐  │
        │            │   │ ollama  │◄─────│ ollama-pull  │  │
        │ HTTP :8000 │   │ :11434  │ pull│ (one-shot)   │  │
        ▼            │   └────┬────┘      └──────────────┘  │
   ┌─────────┐       │        │ HTTP (compose network)      │
   │ lua-gen │       │        ▼                             │
   │   api   │───────┼──► httpx ──► Ollama /api/generate    │
   └─────────┘       │        │                             │
        │            │        │                             │
        │            │   ┌────┴────┐                        │
        │            │   │ volume │  model weights         │
        │            │   │ ollama │                        │
        │            │   └────────┘                        │
        └────────────┴──────────────────────────────────────┘
```

- **api** не ходит в интернет за LLM: только к **ollama** по `OLLAMA_BASE_URL`.

---

## 2. Request flow (`POST /generate`)

```
  Client                          api (FastAPI)                    Ollama
    │                                  │                              │
    │  POST /generate {prompt, ctx}    │                              │
    │─────────────────────────────────►│                              │
    │                                  │── edit? clar? ──► branch     │
    │                                  │── retrieve_for_generation      │
    │                                  │── build full_prompt            │
    │                                  │──────────────────────────────►│ gen1
    │                                  │◄──────────────────────────────┤
    │                                  │── extract_lua_block            │
    │                                  │── validate_lua (luac)          │
    │                                  │                                │
    │                                  │  if not syntax_ok:             │
    │                                  │──────────────────────────────►│ review
    │                                  │◄──────────────────────────────┤
    │                                  │── extract + validate           │
    │  JSON response                   │                              │
    │◄─────────────────────────────────│                              │
```

---

## 3. Generation + reflexion flow (логика)

```
                    ┌─────────────┐
                    │   prompt    │
                    └──────┬──────┘
                           ▼
              ┌──────────────────────┐
              │ needs_clarification? │──yes──► clarify LLM ──► return
              └──────────┬───────────┘
                         │ no
                         ▼
              ┌──────────────────────┐
              │  retrieve (top-k)   │
              └──────────┬───────────┘
                         ▼
              ┌──────────────────────┐
              │   Ollama call #1     │  (MODEL_NAME; fallback on infra)
              └──────────┬───────────┘
                         ▼
              ┌──────────────────────┐
              │  extract ```lua      │
              └──────────┬───────────┘
                         ▼
              ┌──────────────────────┐
              │  validate_lua        │
              └──────────┬───────────┘
                         │
            syntax_ok?   │
                 ┌───────┴───────┐
                yes             no
                 │               │
                 │               ▼
                 │    ┌──────────────────────┐
                 │    │  Ollama call #2      │  reflexion prompt
                 │    │  (review)            │
                 │    └──────────┬───────────┘
                 │               ▼
                 │    ┌──────────────────────┐
                 │    │ extract + validate │
                 │    └──────────┬───────────┘
                 │               │
                 └───────┬───────┘
                         ▼
              ┌──────────────────────┐
              │  final JSON response │
              └──────────────────────┘
```

---

## 4. Fallback vs reflexion (разные оси)

```
  INFRA FAILURE (timeout, 5xx, …)
         │
         ▼
  ┌──────────────┐     success      ┌─────────────┐
  │ MODEL_NAME   │─────────────────►│  use reply  │
  └──────┬───────┘                    └─────────────┘
         │ fail
         ▼
  ┌──────────────┐
  │FALLBACK_MODEL│
  └──────────────┘


  VALIDATION: syntax_ok == false after call #1
         │
         ▼
  ┌──────────────┐
  │ reflexion #2 │  (same MODEL_NAME path; fallback only if call #2 infra fails)
  └──────────────┘
```
