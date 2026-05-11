---
name: e2e-reporter
description: "Automated E2E testing and evidence collection using Puppeteer and Docker Compose. Use when you need to: (1) Run a full stack solution in a clean containerized environment, (2) Verify application flows with real browser execution, (3) Capture screenshots for progress reports, (4) Inspect API responses in a live environment, (5) Generate verifiable evidence of feature completion."
---

# E2E Reporter Skill

This skill automates the process of running a full-stack application via Docker Compose, performing user actions in a real browser, and collecting evidence (screenshots and API logs) for reporting.

## Core Capabilities

1. **Full-Stack Containerization**: Automatically boots up the entire solution using `docker compose`.
2. **Health Monitoring**: Waits for the web frontend to be responsive before starting tests.
3. **Visual Verification**: Take high-resolution mobile/desktop screenshots of any app flow.
4. **API Inspection**: Intercept and log all `/api/` network traffic during the test.
5. **Structured Reporting**: Generate a Markdown report combining visual evidence and technical logs.

## Workflow

### 1. Preparation
Ensure you have a `docker-compose.yml` file and the application code is ready.

### 2. Define Actions
Create a JSON array of actions to perform:
```json
[
  { "type": "wait", "ms": 2000, "description": "Initial Load" },
  { "type": "type", "selector": "#dest", "text": "Envigado", "description": "Search for destination" },
  { "type": "click", "selector": "button.btn-go", "description": "Confirm navigation" }
]
```

### 3. Run Containerized E2E
Use the shell runner to manage the lifecycle:
```bash
bash scripts/docker_e2e_runner.sh <compose_file> <target_url> '<actions_json>' <output_dir>
```

### 4. Generate Report
Use the data from `results.json` to populate the `references/template-report.md`.

## Components

- **docker_e2e_runner.sh**: Orchestrates the Docker lifecycle (up/down) and service health checks.
- **capture_evidence.js**: The Puppeteer engine that drives the browser and captures data.
- **template-report.md**: A professional template for summarizing evidence.

## Best Practices

- **Clean Slate**: Always use the Docker runner to ensure a fresh environment for every test.
- **Timeouts**: The runner waits up to 60 seconds for services. Ensure your images build/boot within this window or adjust the script.
- **Mobile First**: Default viewport is 375x812 (Mobile).
- **Cleanup**: The skill automatically runs `docker compose down` after execution to save resources.
