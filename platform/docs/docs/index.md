---
title: Prometheus
description: Central documentation for the Prometheus multi-agent analysis platform
icon: lucide/book-open
---

# Prometheus Platform

Welcome to the Prometheus documentation. This site serves as the central reference for architecture, usage, and development.

## What is Prometheus?

Prometheus is a multi-agent analysis platform for nuclear engineering, built as part of the Genesis challenge for "Delivering Nuclear Energy That is Faster, Safer, Cheaper." Users interact through a Chainlit chat interface that routes queries to specialist AI agents for materials analysis, safety assessment, and design workflows.

## Documentation

- [Platform](prometheus-platform.md) -- Chainlit frontend + multi-agent architecture
- [platformctl](platformctl/index.md) -- Set up, check and troubleshoot the platform from one command
- [API](prometheus-api.md) -- StorageClient and PrometheusAgent Python toolkit
- [Agent Template](prometheus-agent-template.md) -- Scaffolding tool for creating new A2A agents
- [Workflow Templates](workflow-templates.md) -- Reusable platform- and agent-owned workflow schema and authoring guide
- [Contributing](contributing.md) -- How to set up your local environment, write docs, and use the available markdown features

### Architecture & guides

- [Architecture](dev-docs/architecture.md) -- Full system architecture with diagrams
- [Adding agents](dev-docs/adding-agents.md) -- How to create and register new specialist agents
- [Artifacts](dev-docs/artifacts.md) -- Artifact types, handling, and rendering
- [Message and artifact requirements](dev-docs/message-artifact-requirements.md) -- Target wire-format requirements for multi-agent messaging and artifact rendering
- [Visualization plugins](dev-docs/visualization-plugins.md) -- MeshViewer (Exodus/STL), IFCViewer, MermaidViewer, DynamicForm, PlanViewer
- [Migration guide](dev-docs/migration.md) -- What changed from the original projects and why
