# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Development Commands

# Backend(Python)
- 使用uv管理python库，不要直接使用pip
- 修改代码后，通过ruff、mypy、pytest检验
# Frontend
- 使用pnpm管理依赖，不要使用npm
- 修改代码后，通过pnpm lint/typecheck/build 

## Project Architecture
需要了解项目架构，阅读@docs\architecture.md