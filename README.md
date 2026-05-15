# Urbantrace

## Overview

Urbantrace is a prototype AI-powered research assistant for exploring structured property data through natural language.

The assistant allows users to ask questions about properties, ownership, transactions, and market statistics. It uses an LLM for intent understanding and response formatting, while deterministic Python tools handle the actual data filtering, joins, calculations, and validation.

The main design principle is:

> The LLM plans and explains; deterministic tools execute.

This makes the system easier to debug, more auditable, and less likely to hallucinate unsupported property records or statistics.

---

## Key Features

- Natural-language property search
- Ownership lookup
- Transaction and market-stat analysis
- Tool/function-calling architecture
- Deterministic local Python logic for calculations and filtering
- Lightweight session memory for follow-up questions
- Clear handling of unsupported or ambiguous requests
- CLI and simple web/server interface
- Modular project structure for future extension

---

## Project Structure

```text
Urbantrace/
│
├── app.py                              # CLI entry point
├── server.py                           # Web/server entry point
├── agent.py                            # Core agent logic and LLM tool orchestration
├── tools.py                            # Tool definitions and data query functions
├── data_loader.py                      # CSV loading, validation, and preprocessing
├── memory.py                           # Lightweight session memory for follow-up queries
│
├── static/
│   └── index.html                      # Simple web interface
│
├── data/
│   ├── properties.csv                  # Property records
│   ├── transactions.csv                # Transaction/sales records
│   ├── ownership.csv                   # Ownership records
│   └── DATA_DICTIONARY.md              # Field definitions and schema notes
│
├── architecture/
│   └── AI_Search_Assistant_Architecture.md
│
├── AI_Search_Assistant_Architecture.md # Architecture document copy
├── CLAUDE.md                           # Claude Code / AI development notes
├── testquestions.txt                   # Example test prompts
├── requirements.txt                    # Python dependencies
├── README.md                           # Project documentation
│
├── .env.example                        # Example environment variables
├── .env                                # Local environment variables, not committed
├── .gitignore                          # Git ignore rules
│
├── .venv/                              # Local virtual environment, not committed
└── __pycache__/                        # Python cache files, not committed
