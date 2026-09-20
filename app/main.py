"""Laya prediction HTTP API.

Loads one or more Laya checkpoints behind a Router and serves typed decisions.
Auth supports API keys (`API_KEYS`, comma-separated) and/or HTTP Basic
(`BASIC_AUTH`, comma-separated user:password pairs); it is disabled when neither
is set. FastAPI serves the OpenAPI schema at /openapi.json and docs at /docs.
"""

import base64
import os
import secrets
import threading
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, ConfigDict, Field, model_validator

API_KEYS = [k.strip() for k in os.environ.get("API_KEYS", "").split(",") if k.strip()]

BASIC_AUTH: list[tuple[str, str]] = []
for _pair in os.environ.get("BASIC_AUTH", "").split(","):
    if ":" in _pair:
        _user, _password = _pair.split(":", 1)
        BASIC_AUTH.append((_user.strip(), _password.strip()))

AUTH_ENABLED = bool(API_KEYS or BASIC_AUTH)
MAX_BULK_ITEMS = int(os.environ.get("MAX_BULK_ITEMS", "256"))

# Checkpoints to keep resident at startup (comma-separated).
MODELS = [m.strip() for m in os.environ.get("MODELS", "english").split(",") if m.strip()]
# Optional override for the bundled repo (e.g. a local path or a mirror).
MODEL_ID = os.environ.get("MODEL_ID", "convaiinnovations/laya")
MODEL_SUBFOLDER = os.environ.get("MODEL_SUBFOLDER") or None
DEVICE = os.environ.get("DEVICE", "cpu")

AVAILABLE_MODELS = ("english", "multilingual", "typed-decisions")
ModelName = Literal["english", "multilingual", "typed-decisions"]

_state: dict[str, Any] = {}
_lock = threading.Lock()


def _build_router() -> Any:
    from laya import Router

    models = None
    if MODEL_ID != "convaiinnovations/laya" or MODEL_SUBFOLDER:
        models = {
            name: (MODEL_ID, MODEL_SUBFOLDER if name == "english" else name)
            for name in AVAILABLE_MODELS
        }
    router = Router(models=models, device=DEVICE)
    router.preload(MODELS)
    return router


@asynccontextmanager
async def lifespan(app: FastAPI):
    _state["router"] = _build_router()
    yield
    _state.clear()


app = FastAPI(
    title="Laya API",
    version="0.5.0",
    lifespan=lifespan,
    description=(
        "Run Laya typed decisions (choice / score / noul) over text, JSON objects "
        "or conversation turns, using your own questions or a built-in preset. "
        "Requests are auto-routed to the best checkpoint, or pinned with `model`.\n\n"
        "Authenticate with an API key (`X-API-Key` or `Authorization: Bearer`) or "
        "HTTP Basic, whichever is configured on the server."
    ),
    openapi_tags=[
        {"name": "meta", "description": "Health, models, language detection and presets."},
        {"name": "predict", "description": "Typed decision prediction."},
    ],
)

State = str | dict[str, Any] | list[Any]
CriteriaValue = Any  # str, number, bool, list or dict; rendered as compact JSON

_PRESET_NAMES = ("triage", "email", "guard", "moderation", "router")
PresetName = Literal["triage", "email", "guard", "moderation", "router"]

_presets_cache: dict[str, dict[str, Any]] = {}


def _presets() -> dict[str, dict[str, Any]]:
    """Built-in question sets shipped with laya (imported lazily)."""
    if not _presets_cache:
        from laya import (
            email_questions,
            guard_questions,
            moderation_questions,
            router_questions,
            triage_questions,
        )

        _presets_cache.update(
            {
                "triage": triage_questions(),
                "email": email_questions(),
                "guard": guard_questions(),
                "moderation": moderation_questions(),
                "router": router_questions(),
            }
        )
    return _presets_cache


# --------------------------------------------------------------------------- models
class ChoiceQuestion(BaseModel):
    """Pick one labelled option, e.g. a routing department."""

    type: Literal["choice"]
    instructions: str = Field(..., description="What to decide, phrased as a question.")
    criteria: dict[str, CriteriaValue] | list[CriteriaValue] | None = Field(
        default=None,
        description=(
            "Option label -> description, or a plain list of labels. Descriptions may be "
            "strings or any JSON value (rendered as compact JSON)."
        ),
        examples=[{"billing": "invoices, payments, refunds", "technical": ["bugs", "outages"]}],
    )


class ScoreQuestion(BaseModel):
    """Rate on an ordered scale, e.g. urgency."""

    type: Literal["score"]
    instructions: str
    criteria: list[CriteriaValue] = Field(
        ...,
        description="Ordered levels, lowest first. Each may be any JSON value.",
        examples=[["low", {"level": "high", "sla_minutes": 60}]],
    )


class NoulQuestion(BaseModel):
    """Yes/no decision without a learned neutral class (n-o-u-l)."""

    type: Literal["noul"]
    instructions: str
    criteria: dict[str, CriteriaValue] | None = Field(
        default=None,
        description="Optional `false`/`true` descriptions (any JSON value).",
        examples=[{"true": "phishing or fraud", "false": "a legitimate email"}],
    )


Question = Annotated[ChoiceQuestion | ScoreQuestion | NoulQuestion, Field(discriminator="type")]


def _question_example() -> dict[str, Any]:
    return {
        "department": {
            "type": "choice",
            "instructions": "Which team should handle this request?",
            "criteria": {
                "billing": "invoices, payments, refunds",
                "technical": "bugs and outages",
                "sales": "new purchases",
            },
        },
        "urgency": {
            "type": "score",
            "instructions": "How urgent is this request?",
            "criteria": ["not urgent", "soon", "critical"],
        },
        "refund": {
            "type": "noul",
            "instructions": "Does the customer ask for money back?",
        },
    }


class PredictRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "state": "I was billed twice. Please refund the duplicate today.",
                    "questions": _question_example(),
                },
                {"state": "Hi, we were billed twice for March.", "preset": "triage"},
            ]
        }
    )

    state: State = Field(..., description="Text, JSON object, or conversation turns to analyse.")
    questions: dict[str, Question] | None = Field(
        default=None, description="Map of question id -> typed question definition."
    )
    preset: PresetName | None = Field(
        default=None, description="Built-in question set to use instead of `questions`."
    )
    model: ModelName | None = Field(
        default=None, description="Pin a checkpoint; omit to auto-route by language."
    )

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "PredictRequest":
        if (self.questions is None) == (self.preset is None):
            raise ValueError("Provide exactly one of `questions` or `preset`")
        return self


class BulkItem(BaseModel):
    """One state with optional per-item questions and model override."""

    state: State
    questions: dict[str, Question] | None = Field(
        default=None, description="Overrides the request-level questions for this item."
    )
    model: ModelName | None = Field(
        default=None, description="Overrides the request-level model for this item."
    )


class BulkPredictRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "states": [
                        "I was billed twice. Please refund the duplicate today.",
                        "The app crashes on launch.",
                    ],
                    "questions": _question_example(),
                },
                {
                    "items": [
                        {"state": "I was billed twice."},
                        {"state": "The app crashes.", "model": "english"},
                    ],
                    "preset": "triage",
                },
            ]
        }
    )

    states: list[State] | None = Field(
        default=None,
        min_length=1,
        description="States to classify with the shared `questions`/`preset`.",
    )
    questions: dict[str, Question] | None = Field(
        default=None, description="Questions applied to each state."
    )
    preset: PresetName | None = Field(default=None, description="Preset questions for each state.")
    model: ModelName | None = Field(
        default=None, description="Pin a checkpoint for all states; omit to auto-route."
    )
    items: list[BulkItem] | None = Field(
        default=None,
        min_length=1,
        description="Per-state items, each optionally overriding questions and model.",
    )

    @model_validator(mode="after")
    def _shape(self) -> "BulkPredictRequest":
        if self.items and self.states:
            raise ValueError("Provide either `items` or `states`, not both")
        if not self.items and not self.states:
            raise ValueError("Provide `items` or `states`")
        if self.questions is not None and self.preset is not None:
            raise ValueError("Provide either `questions` or `preset`, not both")
        if self.states and self.questions is None and self.preset is None:
            raise ValueError("`states` requires `questions` or `preset`")
        return self


class ActionResult(BaseModel):
    act_probability: float = Field(..., description="Probability the model acted at all.")


class ChoiceAnswer(BaseModel):
    type: Literal["choice"]
    choice: str
    probabilities: dict[str, float]
    confidence: float
    action: ActionResult


class ScoreAnswer(BaseModel):
    type: Literal["score"]
    score: float = Field(..., description="Expected value on the 0-based criteria scale.")
    legend: dict[str, str]
    probabilities: dict[str, float]
    confidence: float
    action: ActionResult


class NoulAnswer(BaseModel):
    type: Literal["noul"]
    noul: float
    confidence: float
    action: ActionResult


Answer = Annotated[ChoiceAnswer | ScoreAnswer | NoulAnswer, Field(discriminator="type")]


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int


class Routing(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    reason: str | None = None


class PredictResponse(BaseModel):
    # extra="allow" keeps any future/additional fields the library returns.
    model_config = ConfigDict(extra="allow")

    model: str
    answers: dict[str, Answer]
    usage: Usage
    routing: Routing | None = Field(
        default=None, description="How the checkpoint was chosen (auto-route or pinned)."
    )


class BulkItemResult(BaseModel):
    ok: bool
    result: PredictResponse | None = None
    error: str | None = None


class BulkPredictResponse(BaseModel):
    count: int
    results: list[BulkItemResult]


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    device: str
    auth_enabled: bool
    auth_methods: list[str]
    models: list[str] = Field(..., description="Checkpoints currently resident.")
    available_models: list[str]


class ModelsResponse(BaseModel):
    available: list[str]
    loaded: list[str]


class DetectRequest(BaseModel):
    state: State


class EmailStateRequest(BaseModel):
    subject: str = ""
    body: str
    sender: str | None = None
    clean: bool = Field(default=True, description="Strip quoted history, signatures, disclaimers.")


# ----------------------------------------------------------------------------- auth
def _valid_api_key(token: str) -> bool:
    return any(secrets.compare_digest(token, key) for key in API_KEYS)


def _valid_basic(header: str) -> bool:
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "basic" or not value:
        return False
    try:
        decoded = base64.b64decode(value.strip()).decode("utf-8")
    except Exception:
        return False
    user, _, password = decoded.partition(":")
    return any(
        secrets.compare_digest(user, u) and secrets.compare_digest(password, p)
        for u, p in BASIC_AUTH
    )


def require_auth(
    authorization: Annotated[str | None, Header(include_in_schema=False)] = None,
    x_api_key: Annotated[str | None, Header(include_in_schema=False)] = None,
) -> None:
    """Allow the caller via API key or HTTP Basic. No-op when auth is unconfigured."""
    if not AUTH_ENABLED:
        return
    if x_api_key and _valid_api_key(x_api_key.strip()):
        return
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value and _valid_api_key(value.strip()):
            return
        if _valid_basic(authorization):
            return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing credentials",
        headers={"WWW-Authenticate": 'Basic realm="laya", Bearer'},
    )


def _router() -> Any:
    router = _state.get("router")
    if router is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet")
    return router


def _dump(questions: dict[str, Question]) -> dict[str, dict[str, Any]]:
    """Laya's runtime expects plain dicts, not Pydantic models."""
    return {qid: q.model_dump(exclude_none=True) for qid, q in questions.items()}


def _resolve(
    questions: dict[str, Question] | None, preset: PresetName | None
) -> dict[str, dict[str, Any]]:
    if preset is not None:
        return _presets()[preset]
    return _dump(questions or {})


_AUTH_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Missing or invalid credentials"},
    503: {"description": "Model not loaded yet"},
}


# ------------------------------------------------------------------------- endpoints
@app.get("/healthz", tags=["meta"], response_model=HealthResponse, summary="Health check")
def healthz() -> HealthResponse:
    router = _state.get("router")
    return HealthResponse(
        status="ok",
        model_loaded=router is not None,
        device=DEVICE,
        auth_enabled=AUTH_ENABLED,
        auth_methods=[
            m for m, on in (("apikey", bool(API_KEYS)), ("basic", bool(BASIC_AUTH))) if on
        ],
        models=list(router.loaded) if router is not None else [],
        available_models=list(AVAILABLE_MODELS),
    )


@app.get(
    "/models",
    tags=["meta"],
    response_model=ModelsResponse,
    summary="List checkpoints",
    dependencies=[Depends(require_auth)],
    responses=_AUTH_RESPONSES,
)
def list_models() -> ModelsResponse:
    """Available checkpoints and which are currently resident."""
    router = _router()
    return ModelsResponse(available=list(AVAILABLE_MODELS), loaded=list(router.loaded))


@app.get(
    "/presets",
    tags=["meta"],
    summary="List built-in question presets",
    dependencies=[Depends(require_auth)],
    responses=_AUTH_RESPONSES,
)
def list_presets() -> dict[str, dict[str, Any]]:
    """Return the ready-to-use question sets (triage/email/guard/moderation/router)."""
    return _presets()


@app.post(
    "/detect",
    tags=["meta"],
    summary="Detect script and language",
    dependencies=[Depends(require_auth)],
    responses=_AUTH_RESPONSES,
)
def detect(request: DetectRequest) -> dict[str, Any]:
    """Report script, best-effort language and `is_english` for a state (what routing uses)."""
    from laya import detect_language

    return detect_language(request.state)


@app.post(
    "/email/state",
    tags=["meta"],
    summary="Build a clean email state",
    dependencies=[Depends(require_auth)],
    responses=_AUTH_RESPONSES,
)
def email_state_endpoint(request: EmailStateRequest) -> dict[str, Any]:
    """Clean an email body and structure it as a state for `/predict`."""
    from laya import email_state

    return email_state(request.subject, request.body, sender=request.sender, clean=request.clean)


@app.post(
    "/predict",
    tags=["predict"],
    response_model=PredictResponse,
    response_model_exclude_none=True,
    summary="Predict one state",
    dependencies=[Depends(require_auth)],
    responses=_AUTH_RESPONSES,
)
def predict(request: PredictRequest) -> PredictResponse:
    """Run typed questions over a single state and return calibrated answers."""
    router = _router()
    questions = _resolve(request.questions, request.preset)
    with _lock:
        result = router.predict(request.state, questions, model=request.model)
    return PredictResponse.model_validate(result)


@app.post(
    "/predict/bulk",
    tags=["predict"],
    response_model=BulkPredictResponse,
    response_model_exclude_none=True,
    summary="Predict many states",
    dependencies=[Depends(require_auth)],
    responses=_AUTH_RESPONSES,
)
def predict_bulk(request: BulkPredictRequest) -> BulkPredictResponse:
    """Run typed questions over many states.

    Accepts either `states` with shared `questions`/`preset`, or `items` where each
    state can override its questions and model. Laya's public API predicts one state
    at a time (its internals can batch, but the public `Agent.predict` cannot), so
    this loops. Per-state errors are isolated and returned inline.
    """
    if request.items:
        jobs = [
            (
                item.state,
                _resolve(item.questions or request.questions, request.preset),
                item.model or request.model,
            )
            for item in request.items
        ]
    else:
        questions = _resolve(request.questions, request.preset)
        jobs = [(state, questions, request.model) for state in request.states or []]

    if len(jobs) > MAX_BULK_ITEMS:
        raise HTTPException(
            status_code=422,
            detail=f"Too many states: {len(jobs)} > MAX_BULK_ITEMS={MAX_BULK_ITEMS}",
        )

    router = _router()
    results: list[BulkItemResult] = []
    with _lock:
        for state, questions, model in jobs:
            try:
                results.append(
                    BulkItemResult(
                        ok=True,
                        result=PredictResponse.model_validate(
                            router.predict(state, questions, model=model)
                        ),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - report per-item failure
                results.append(BulkItemResult(ok=False, error=str(exc)))
    return BulkPredictResponse(count=len(results), results=results)


# ------------------------------------------------------------------------ openapi
def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )
    components = schema.setdefault("components", {})
    components.setdefault("securitySchemes", {}).update(
        {
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
                "description": "A key from the server's API_KEYS.",
            },
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "description": "An API key sent as a bearer token.",
            },
            "BasicAuth": {
                "type": "http",
                "scheme": "basic",
                "description": "A user:password from the server's BASIC_AUTH.",
            },
        }
    )
    # Any one scheme is sufficient (OpenAPI OR semantics). /healthz stays open.
    security = [{"ApiKeyAuth": []}, {"BearerAuth": []}, {"BasicAuth": []}]
    for path, item in schema.get("paths", {}).items():
        if path == "/healthz":
            continue
        for method, operation in item.items():
            if method in {"get", "post", "put", "patch", "delete"} and isinstance(operation, dict):
                operation["security"] = security
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]
