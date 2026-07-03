# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Development Commands

# Backend(Python)
- 使用uv管理python库，不要直接使用pip
- 修改代码后，通过ruff、mypy、pytest检验
# Frontend
- 项目位于/web下
- 使用pnpm管理依赖，不要使用npm
- 修改代码后，通过pnpm lint/typecheck/build
- 测试框架使用vitest + react-testing-library，测试文件放在web工程的test路径下，具体路径和被测试的文件对齐 

## Project Architecture
需要了解项目架构，阅读@docs\architecture.md