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
    risk: str = "medium"  # low / medium / high


class GeneratedTest(BaseModel):
    filename: str
    content: str
    target_call_site: str


class AnalysisResult(BaseModel):
    changed_functions: List[ChangedFunction]
    call_sites: List[CallSite]
    untested_high_risk: List[CallSite]
    generated_tests: List[GeneratedTest]
    summary: str
    risk_score: int = Field(ge=0, le=100)  # 0 = safe, 100 = very risky


class AnalyzeRequest(BaseModel):
    pr_url: Optional[str] = None
    diff_text: Optional[str] = None
    repo_path: Optional[str] = None  # for local testing