# AppliedAI AI Engineer Interview - Exercise 2

## 2 Pipeline Deliverable

The goal of this offline pipeline deliverable is to check if the candidate can formulate assumptions, take directions, and produce a working end-to-end solution on a business case.

### 2.1 Medical Coding

Medical organizations translate clinical encounter notes into standardized diagnosis and procedure codes for billing, reporting, and record-keeping. This process is governed by strict coding rules and requires high accuracy.

**Goal** &nbsp; Design and implement a system that reviews clinical notes and produces structured coding suggestions that can be validated by a human reviewer.

**Input Format** &nbsp; Each input consists of a clinical note in plain text format. Notes are unstructured, narrative-heavy, and may span multiple pages. A single note may reference multiple diagnoses and procedures.

**Output Format** &nbsp; The system must produce:

- Suggested diagnosis codes (ICD-10) with confidence scores
- Suggested procedure codes (CPT) with confidence scores
- Evidence references supporting each suggested code
- Warnings for missing information, ambiguity, or potential conflicts
- A structured payload suitable for human review and override

**Constraints**

- The space of possible codes is large (tens of thousands)
- An LLM may be used for extraction and reasoning
- Outputs must be structured, auditable, and reproducible

**Deliverable** &nbsp; Design a pipeline that:

- Ingests raw clinical notes
- Extracts relevant medical facts and signals
- Produces candidate diagnosis and procedure codes
- Assigns confidence scores and supporting evidence
- Emits a reviewer-ready result

Provide a minimal but complete implementation in a GitHub repository that:

- Can be executed locally or in a container
- Demonstrates ingestion, processing, and output
- Produces structured, validated results
- Includes logging or tracing suitable for audit

Provide a PDF document (1–2 pages) describing:

- Overall architecture and data flow
- Code retrieval or filtering strategy
- LLM usage and prompting approach
- Key technical decisions and trade-offs
- Limitations and possible extensions
