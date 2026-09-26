from pydantic import BaseModel, Field
from typing import List, Optional


class ChangedFunction(BaseModel):
    name: str
    file: str
    lineno: int
    end_lineno: Optional[int] = None


class CallSite(BaseModel):
    file: str
    lineno: int
    function_name: str
    code_line: str
    is_tested: bool = False
    risk: str = "medium"
    risk_score: int = Field(default=50, ge=0, le=100)
    caller_name: Optional[str] = None
    caller_qualname: Optional[str] = None
    target_qualname: Optional[str] = None
    module: Optional[str] = None
    target_module: Optional[str] = None
    caller_params: List[str] = Field(default_factory=list)
    caller_is_method: bool = False
    patch_target: Optional[str] = None
    coverage_reason: Optional[str] = None
    impact_reason: Optional[str] = None


class GeneratedTest(BaseModel):
    filename: str
    content: str
    target_call_site: str
    generated: bool = True
    syntax_ok: bool = False
    pytest_passed: Optional[bool] = None
    pytest_output: Optional[str] = None
    attempts: int = 0
    error: Optional[str] = None


class AnalysisResult(BaseModel):
    analysis_engine: str = "ast"
    changed_functions: List[ChangedFunction]
    call_sites: List[CallSite]
    untested_high_risk: List[CallSite]
    generated_tests: List[GeneratedTest]
    summary: str
    risk_score: int = Field(ge=0, le=100)
    risk_explanation: str = ""
    test_execution_status: str = ""
    validation_errors: List[str] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    pr_url: Optional[str] = None
    diff_text: Optional[str] = None
    repo_path: Optional[str] = None
    engine: Optional[str] = "ast"


class LLMStatus(BaseModel):
    status: str
    detail: str = ""
    model: Optional[str] = None
    server_url: Optional[str] = None
