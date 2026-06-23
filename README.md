# T-RADAR: Simulating Trademark Examination as an Interactive Retrieval Interface for Conflict Risk Assessment

> **Authors**: Yongdeuk Seo, Noah Lee, Hyun-seok Min, Sungchul Choi

[![Project Page](https://img.shields.io/badge/Project-Page-1a73e8?logo=Google%20Chrome&logoColor=white)](https://yongchoooon.github.io/tradar/) [![Demo](https://img.shields.io/badge/Demo-T--RADAR-ffcc4d?&logoColor=white)](https://do7ajfzdgr22.cloudfront.net/)

## 🎉 Congratulations!
This repository is the official implementation of the paper accepted to the ACM SIGIR 2026 Demonstration Track: [Link](https://sigir2026.org/en-AU/pages/program/accepted-papers#:~:text=%5Bde%5D%20T%2DRADAR%3A%20Simulating%20Trademark%20Examination%20as%20an%20Interactive%20Retrieval%20Interface%20for%20Conflict%20Risk%20Assessment)

---
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

## Reproducibility
This public repository contains the application code, UI assets, and deployment definitions for T-RADAR. It does not contain everything needed to reproduce the production system end to end.

The deployed system depends on:
- a proprietary trademark corpus licensed from [KIPRIS Plus](https://plus.kipris.or.kr/portal/main.do),
- prebuilt PostgreSQL/pgvector and OpenSearch indices,
- AWS infrastructure, secrets, and deployment configuration,
- a desktop GPU worker used for retrieval offloading.

For legal, licensing, and operational reasons, the production data, search indices, and secrets are not redistributed in this repository. Full production reproduction is therefore not possible from this repository alone.

## What You Can Run
You can still inspect and run parts of the project locally:

```bash
pip install -r requirements.txt
pytest

cd frontend
npm ci
npm run build
```

If you want to adapt the system to your own data and infrastructure, use the following documents as the implementation reference:
- `README_dev.md`
- `markdown/tradar_setup_guide.md`
- `markdown/search-pipeline.md`

## Data Availability
The production trademark corpus is not included in this repository. Part of the dataset was obtained through a paid [KIPRIS Plus](https://plus.kipris.or.kr/portal/main.do) license and cannot be publicly shared or redistributed here. The repository only includes materials that can be distributed directly, such as the goods/services support files under `app/data/goods_services/`.

## Licensing
The accompanying ACM SIGIR Demo paper is intended to be published under CC BY 4.0. That publication license does not automatically apply to the code, assets, or data in this repository. Repository-level rights are defined separately in `LICENSE`, and third-party or proprietary datasets remain subject to their own terms.
