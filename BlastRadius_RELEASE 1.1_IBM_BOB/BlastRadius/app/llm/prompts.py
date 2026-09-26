"""Prompts for local GGUF impact analysis and pytest generation."""

ANALYSIS_SYSTEM = """You are a senior Python engineer performing blast-radius analysis of a code change.
You work only from the provided local project context. Do not invent files, functions, or APIs.
Reply with a single JSON object. No markdown, no commentary outside JSON.
"""

ANALYSIS_USER = """Project language:
Python

Changed code (unified diff):
{diff}

Relevant source:
{source}

Affected modules:
{modules}

Existing tests:
{tests}

Task:
Analyze the code change and determine which functions, methods and execution paths may be affected.

Identify:
1. Changed functions
2. Callers of changed functions
3. Potentially affected execution paths
4. Paths that appear to lack tests
5. Regression risks
6. A concise explanation of why each risky path matters

Return JSON with this exact shape:
{{
  "changed_functions": [{{"name": "", "file": "", "lineno": 0}}],
  "call_sites": [{{
    "file": "",
    "lineno": 0,
    "function_name": "",
    "code_line": "",
    "caller_name": "",
    "caller_qualname": "",
    "is_tested": false,
    "risk": "high",
    "risk_score": 80,
    "coverage_reason": "",
    "impact_reason": "",
    "module": "",
    "caller_params": [],
    "caller_is_method": false
  }}],
  "untested_high_risk": [],
  "risk_score": 0,
  "risk_explanation": "",
  "summary": ""
}}
Use only names that appear in the provided source. risk_score is 0-100.
"""

TEST_SYSTEM = """You are a Python pytest test generator.
Use only real functions and imports from the provided project.
Do not invent APIs. Do not modify production code.
Return only valid Python test code.
"""

TEST_USER = """You are a Python pytest test generator.
Changed function:
{changed}

Affected caller:
{caller}

Why the path is risky:
{reason}

Relevant source:
{source}

Changed diff:
{diff}

Existing tests:
{tests}

Generate ONE focused regression test.
Requirements:
- use real functions and imports from the provided project
- do not invent APIs
- do not modify production code
- target the affected execution path
- use pytest
- follow the existing project style where possible
- return only valid Python test code
"""

REPAIR_USER = """The previous pytest file failed validation.

Filename:
{filename}

Previous test code:
{code}

Failure:
{error}

Pytest output:
{output}

Relevant source:
{source}

Write a corrected pytest file. Return only valid Python test code.
Keep using real project imports. Do not invent APIs.
"""
