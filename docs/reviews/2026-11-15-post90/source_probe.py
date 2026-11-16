"""Temporary source-extraction probes; no backend imports, DB, config or network."""
import ast
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "devpilot/src"))
from devpilot.qa_signoff_policy import evaluate_signoff_requirement

class DBAPIError(Exception):
    pass

class IntegrityError(DBAPIError):
    pass

class Conflict(Exception):
    pass

class NotFound(Exception):
    pass

class Query:
    def __getattr__(self, name):
        return self
    def __call__(self, *args, **kwargs):
        return self
    def __eq__(self, other):
        return self

query = Query()
class ReadResult:
    def __init__(self, rows):
        self.rows = rows
    def scalar_one(self):
        return None
    def mappings(self):
        return self
    def first(self):
        return None
    def all(self):
        return self.rows

class Session:
    def __init__(self, rows, write=False):
        self.rows, self.write = rows, write
    async def execute(self, statement):
        if self.write:
            raise IntegrityError("synthetic duplicate revision")
        return ReadResult(self.rows)

class Factory:
    def __init__(self, rows):
        self.rows = rows
    @asynccontextmanager
    async def __call__(self):
        yield Session(self.rows)
    @asynccontextmanager
    async def begin(self):
        yield Session(self.rows, write=True)

approval_tree = ast.parse((ROOT / "backend/app/evaluation/qa_approvals.py").read_text(encoding="utf-8"))
journal_tree = ast.parse((ROOT / "backend/app/evaluation/dispatch_journal.py").read_text(encoding="utf-8"))
approval_class = next(n for n in approval_tree.body if isinstance(n, ast.ClassDef) and n.name == "ApprovalRepository")
journal_class = next(n for n in journal_tree.body if isinstance(n, ast.ClassDef) and n.name == "DispatchJournalRepository")
methods = [n for n in approval_class.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in {"set_signoff_policy", "approval_signoff_progress"}]
methods.append(next(n for n in journal_class.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_transaction"))
cls = ast.ClassDef(name="ExtractedRepository", bases=[], keywords=[], body=methods, decorator_list=[])
unconfirmed = next(n for n in journal_tree.body if isinstance(n, ast.ClassDef) and n.name == "JournalWriteUnconfirmed")
module = ast.fix_missing_locations(ast.Module(body=[unconfirmed, cls], type_ignores=[]))
ns = {"asyncio": asyncio, "asynccontextmanager": asynccontextmanager, "DBAPIError": DBAPIError, "IntegrityError": IntegrityError, "Conflict": Conflict, "t": query, "select": query, "insert": query, "func": query, "fingerprint": lambda value: "f" * 64}
exec(compile(module, "<unaltered repository methods>", "exec"), ns)
Repository = ns["ExtractedRepository"]
async def no_op(*args, **kwargs):
    pass
Repository._project = no_op
Repository._journal = no_op
Repository._time = lambda self: 1800000000000

async def main():
    repo = Repository()
    repo.sf = Factory([])
    try:
        await repo.set_signoff_policy("owner", "project", required_distinct_approvers=2, expected_previous_revision=0)
    except Exception as error:
        print(json.dumps({"probe": "policy duplicate insert", "expected": "Conflict", "actual": type(error).__name__}))
    repo.sf = Factory([{"revision": i + 1, "decision": "approved", "approver_id": str(i)} for i in range(11)])
    progress = await repo.approval_signoff_progress("owner", "project", "run")
    try:
        evaluate_signoff_requirement(required_distinct_approvers=2, distinct_approved_approvers=progress["distinct_approved_approvers"], latest_decision=progress["latest_decision"])
    except ValueError as error:
        print(json.dumps({"probe": "11 approvers with required=2", "observed": progress["distinct_approved_approvers"], "actual": type(error).__name__}))

    # Preserve the actual route body; remove framework decorators/annotations only.
    router_tree = ast.parse((ROOT / "backend/app/gateway/routers/evaluation_projects.py").read_text(encoding="utf-8"))
    route = next(n for n in router_tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "create_run_approval")
    route.decorator_list = []
    for arg in route.args.args:
        arg.annotation = None
    route.returns = None
    async def absent_project(*args):
        raise NotFound()
    repo._project = absent_project
    async def route_context(request):
        return "other-owner", repo
    route_ns = {"_approval_context": route_context, "approval_identifier": lambda value: value}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[route], type_ignores=[])), "<unaltered route body>", "exec"), route_ns)
    try:
        await route_ns["create_run_approval"]("foreign-project", "run", "a" * 32, SimpleNamespace(), object())
    except Exception as error:
        print(json.dumps({"probe": "foreign-owner project", "expected": "mapped HTTPException 404", "actual_uncaught": type(error).__name__}))

asyncio.run(main())
