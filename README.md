# Urbantrace

## Overview

This project implements a prototype of an AI-powered research assistant for property data. The assistant allows users to query structured datasets (properties, transactions, ownership) using natural language and receive clear, data-driven responses.

The system uses an LLM with tool-calling capabilities to translate user queries into structured operations, execute them on local datasets, and return interpreted results.

---

## Project Structure

```text
part3/
│
├── app.py                  # Entry point (CLI interface)
├── agent.py                # Core agent logic (LLM + tool orchestration)
├── tools.py                # Tool definitions (data query functions)
├── data_loader.py          # Data ingestion and preprocessing
├── memory.py               # Conversation memory (multi-turn support)
│
├── data/
│   ├── properties.csv
│   ├── transactions.csv
│   ├── ownership.csv
│   └── DATA_DICTIONARY.md
│
├── architecture/
│   └── AI_Search_Assistant_Architecture.md
│
├── .env.example            # Environment variable template
├── requirements.txt
├── README.md               # (this file)
└── Part3.mp4               # Demo recording
```

---

## How It Works

### 1. User Query

The user enters a natural language query via the CLI (e.g., “Show SRL-owned properties in Gheorgheni over $2M”).

### 2. Agent Reasoning

The agent:

* Interprets intent using the LLM
* Decides whether a tool is needed
* Selects the appropriate tool and parameters

### 3. Tool Execution

Custom tools in `tools.py`:

* Query structured datasets using pandas
* Perform filtering, aggregation, and joins

### 4. Response Generation

The LLM:

* Interprets tool output
* Formats a clear, user-friendly response

### 5. Memory Handling

* Conversation context is stored in `memory.py`
* Enables follow-up queries and multi-turn reasoning

---

## Implemented Tools

### 1. Property Search Tool

* Filters properties by location, ownership type, and price
* Used for direct lookup queries

### 2. Transaction Analysis Tool

* Aggregates transaction data (e.g., averages, totals)
* Used for trend and comparison questions

### 3. Ownership Lookup Tool

* Identifies SRL vs individual ownership patterns
* Used for ownership-related queries

---

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

---

### 2. Configure Environment

Create a `.env` file based on `.env.example`:

```bash
OPENAI_API_KEY=your_api_key_here
```

---

### 3. Run the Assistant

```bash
python app.py
```

---

## Example Queries

### Data Retrieval

* “Show all SRL-owned properties in Gheorgheni 11201 over $2M”

### Analytical Comparison

* “Compare average property values across neighborhoods (cartiere)”

### Edge Case / Error Handling

* “Show properties owned by celebrities in Mărăști”

---

## Context Management

* Conversation history is stored in memory
* The agent uses prior queries to interpret follow-ups
* Example:

  * User: “Show SRL properties in Gheorgheni”
  * User: “Only those over $2M” → correctly applies filter

---

## Error Handling Strategy

The system handles:

### Ambiguous Queries

* Requests clarification when key parameters are missing

### Unanswerable Questions

* Responds with limitations instead of hallucinating

### Data Gaps

* Returns partial results with explanation

---

## Assumptions

* CSV data is reasonably clean and preprocessed
* Borough and ZIP mappings are consistent
* Ownership classification (SRL vs non-SRL) is derived from ownership names

---

## Limitations

* No real-time data (static CSVs only)
* Limited query optimization for large datasets
* Basic prompt engineering (no fine-tuning or evaluation layer)

---

## Future Improvements

* Add semantic search (vector database)
* Improve tool selection accuracy with structured schemas
* Add web-based UI
* Implement caching and performance optimizations
* Introduce validation layer for tool outputs

---

## Demo

See `Part3.mp4` for:

* System walkthrough
* Example queries
* Error handling demonstration

---

## Notes

This prototype prioritizes clarity, modularity, and explainability over production-scale performance. All design decisions can be explained and extended during a live walkthrough.

---
