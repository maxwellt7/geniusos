# Lifelog Query System: Database Architecture Design

## Executive Summary
This document outlines the optimal database architecture for ingesting, storing, and querying personal lifelog data from the Limitless AI API. The goal is to enable highly accurate, context-aware, and temporally precise conversational querying. Based on current state-of-the-art patterns for AI agent memory, the proposed architecture employs a multi-layer hybrid approach combining a structured relational database, a vector store for semantic search, and a temporal knowledge graph for multi-hop reasoning.

## 1. System Requirements & Data Profile

The Limitless AI API provides hierarchical, temporally-bound conversational data. Each lifelog entry contains metadata such as timestamps, titles, and star status, along with an array of `ContentNode` objects. These nodes represent the structural elements of the conversation, including headings, blockquotes, and paragraphs. They also include crucial context such as speaker identification, start and end timestamps, and precise millisecond offsets [1].

To effectively query this data, the system must handle semantic retrieval, understanding the meaning behind queries rather than relying solely on exact keyword matches. It must also perform relational reasoning to connect disparate concepts across multiple conversations, for example, identifying patterns in advice given by a specific person. Furthermore, the system must maintain strict temporal context, understanding when events occurred, when facts became true, and the sequence of conversations. Finally, strict attribution and provenance are required to trace every generated insight back to the specific speaker and timestamp in the original lifelog.

## 2. Multi-Layer Database Architecture

To meet these complex requirements, the architecture utilizes three specialized storage layers working in concert. This hybrid approach overcomes the limitations of relying on a single database paradigm.

### Layer 1: Structured Storage (PostgreSQL)
PostgreSQL serves as the foundational source of truth for all structured metadata and raw transcript content. It handles exact match filtering, temporal range queries, and user management. This layer is responsible for storing core lifelog metadata, including IDs, titles, and start/end times. It maintains the hierarchical structure of `ContentNode` elements and tracks ingestion status and sync watermarks. PostgreSQL excels at executing precise temporal queries, such as filtering for "conversations from last Tuesday".

### Layer 2: Semantic Vector Storage (pgvector)
By utilizing the `pgvector` extension within PostgreSQL, the system gains powerful semantic search capabilities without the operational overhead of a separate database system. This layer stores mathematical representations, or embeddings, of transcript chunks. It is responsible for executing approximate nearest-neighbor (ANN) searches for semantic similarity. This enables hybrid search queries that combine vector similarity with traditional keyword search using BM25.

### Layer 3: Temporal Knowledge Graph (Neo4j + Graphiti)
The most critical component for advanced reasoning is the temporal knowledge graph. Traditional vector databases struggle with multi-hop reasoning and relationship mapping. We propose using Neo4j integrated with Zep AI's open-source Graphiti engine, which is specifically designed for dynamic agent memory [2]. This layer is responsible for extracting and storing entities such as People, Places, Organizations, and Topics from the transcripts. It maps relationships between these entities, such as `DISCUSSED_TOPIC` or `ATTENDED_MEETING_WITH`. Crucially, it maintains a bi-temporal model that tracks both when a fact was stated in the lifelog and when it was ingested into the system. This enables complex graph traversals to answer relational questions accurately.

## 3. Data Ingestion & Processing Pipeline

The ingestion pipeline transforms the raw, hierarchical data from the Limitless API into optimized formats for all three storage layers.

| Stage | Process Description | Primary Output |
| :--- | :--- | :--- |
| **1. Extraction** | Poll the Limitless API `/v1/lifelogs` endpoint using cursor pagination to extract raw JSON responses. | Raw JSON payloads |
| **2. Structural Parsing** | Flatten the nested `ContentNode` hierarchy into sequential utterances while preserving speaker attribution and millisecond offsets. | Structured PostgreSQL records |
| **3. Semantic Chunking** | Group sequential utterances into semantically coherent chunks based on topic shifts, ensuring chunks overlap slightly to preserve context boundaries. | Text chunks for embedding |
| **4. Embedding Generation** | Process text chunks through an embedding model like OpenAI `text-embedding-3-small` to generate high-dimensional vectors. | Vector arrays for pgvector |
| **5. Entity Extraction** | Utilize a multi-stage pipeline combining spaCy for basic NER with LLM extraction to identify key entities and relationships within the chunks. | Graph nodes and edges |
| **6. Graph Integration** | Merge extracted entities into the Neo4j graph via Graphiti, updating temporal validity windows and resolving entity duplication. | Updated Temporal Knowledge Graph |

## 4. Intelligent Query Routing

When a user asks a question, the system must determine the optimal retrieval strategy. A query routing layer analyzes the user's prompt and orchestrates the retrieval process across the three database layers.

Factual and semantic queries, such as "What did we discuss regarding the new marketing strategy?", are routed primarily to the vector store for semantic similarity search. Relational and multi-hop queries, such as "Who did Sarah recommend for the engineering role, and what companies have they worked for?", are routed to the Neo4j knowledge graph for Cypher traversal. Temporal and filtering queries, such as "Show me all conversations with John from last month", are routed to PostgreSQL for structured date filtering, often combined with vector search for specific topics.

The retrieved context from these sources is then synthesized and provided to the Large Language Model (LLM) to generate the final, accurate response, complete with citations pointing back to the original lifelog timestamps.

## References
[1] Limitless AI API Documentation. Limitless Developer Platform. https://www.limitless.ai/developers
[2] Zep AI. Graphiti: Knowledge graph memory for an agentic world. Neo4j Developer Blog. https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/
