# T-RADAR: Simulating Trademark Examination as an Interactive Retrieval Interface for Conflict Risk Assessment

[![Project Page](https://img.shields.io/badge/Project-Page-1a73e8?logo=Google%20Chrome&logoColor=white)](https://yongchoooon.github.io/tradar/) [![Demo](https://img.shields.io/badge/Demo-T--RADAR-ffcc4d?&logoColor=white)](https://do7ajfzdgr22.cloudfront.net/)

T-RADAR is an interactive trademark clearance system that pairs multimodal retrieval with protocol-driven examination simulation.

![Main UI](figs/main.png)

## Overview
- **Hybrid multimodal retrieval** for candidate discovery (logo image + mark name + goods/services).
- **Agentic simulation** that models an Examiner–Applicant exchange and produces Conflict risk and Registrability scores.
- **Interactive refinement loop** to compare before/after outcomes when users adjust the mark name or goods scope.
- **Grounded judgments** using KIPRIS Office Actions and Decisions of Refusal when available.

## Workflow (Demo)
1. **Query**: input a mark (text, image, or both) and goods/services to retrieve candidates.
2. **Select & Simulate**: choose candidate pairs and run a structured examination simulation.
3. **Refine & Re-simulate**: adjust inputs and re-run to compare outcomes side by side.

## System Pipeline
![System pipeline](figs/pipeline.png)

## Core Methods

### Retrieval
T-RADAR combines BM25 keyword retrieval with embedding-based ANN search. For image queries, DINOv2 and MetaCLIP2 embeddings are fused; for text queries, BM25 candidates are re-ranked by MetaCLIP2 text similarity. Optionally, lightweight LLM-generated name variants can broaden recall before re-ranking.

### Simulation
Each selected pair follows a fixed examination protocol: Examiner raises objections, Applicant rebuts, Examiner adjudicates, Reporter summarizes, and Scorer assigns Conflict risk and Registrability scores. A Final Reporter aggregates results across pairs and highlights high-risk cases. Outputs are streamed to the UI as they complete.

## UI
- A single-screen layout connects retrieval and simulation without leaving the page.
- Candidates are presented as compact cards with similarity scores and goods/services context.
- Simulation results show per-pair reports plus an aggregated batch summary for review prioritization.

<table>
  <tr>
    <td align="center">
      <img src="figs/image_search_results.png" alt="Image retrieval results" width="100%">
      <br>
      <sub>Image retrieval results</sub>
    </td>
    <td align="center">
      <img src="figs/text_search_results.png" alt="Text retrieval results" width="100%">
      <br>
      <sub>Text retrieval results</sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <img src="figs/simulation_results.png" alt="Simulation results" width="100%">
      <br>
      <sub>Simulation results</sub>
    </td>
    <td align="center">
      <img src="figs/simulation_scores.png" alt="Simulation scores" width="100%">
      <br>
      <sub>Simulation scores</sub>
    </td>
  </tr>
</table>

## Deployment (Reference)
- **Frontend**: static build on S3 + CloudFront.
- **Backend**: API on ECS/Fargate behind ALB.
- **Retrieval offload**: a desktop GPU worker connects to local Postgres/pgvector and OpenSearch; the backend communicates with the worker over WebSocket.
- **Optional cloud retrieval**: the search stack can be migrated to RDS and OpenSearch Service.

## License
Unless otherwise stated, this project is for internal use within the Pukyong National University Industrial AI Laboratory.
