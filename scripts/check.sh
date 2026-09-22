#!/usr/bin/env bash
# Quick developer verification script for Ag Attention Bridge
set -e

echo "==> Running Ruff check..."
ruff check src tests

echo "==> Running Ruff format check..."
ruff format --check src tests

echo "==> Running Mypy type checker..."
mypy src

echo "==> Running Pytest with coverage..."
pytest --cov=ag_attention_bridge --cov-report=term-missing

echo "==> All quality checks passed!"
